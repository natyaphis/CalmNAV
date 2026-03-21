from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any
from urllib.parse import quote_plus

import requests

from calmnav.calculator import HoldingsSnapshot, MarketSnapshot, StrategyCapitalStructure
from calmnav.config import Settings

NUMBER_PATTERN = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)")
CURRENCY_SUFFIXES = {
    "K": 1_000,
    "M": 1_000_000,
    "B": 1_000_000_000,
    "T": 1_000_000_000_000,
}
STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0001050446.json"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data/1050446"
STRATEGY_Q4_2025_RESULTS_URL = "https://www.strategy.com/press/strategy-announces-fourth-quarter-2025-financial-results_02-05-2026"
STRATEGY_Q3_2025_RESULTS_URL = "https://www.strategy.com/press/strategy-announces-third-quarter-2025-financial-results_10-30-2025"
STRATEGY_Q2_2025_RESULTS_URL = "https://www.strategy.com/press/strategy-announces-second-quarter-2025-financial-results_07-31-2025"
STRATEGY_Q1_2025_RESULTS_URL = "https://www.strategy.com/press/strategy-announces-first-quarter-2025-financial-results_05-01-2025"
STRATEGY_Q4_2024_RESULTS_URL = (
    "https://www.strategy.com/press/strategy-announces-fourth-quarter-2024-financial-results-and-launches-new-website-strategy-com_02-05-2025"
)
STRATEGY_Q3_2024_RESULTS_URL = (
    "https://www.strategy.com/press/microstrategy-announces-third-quarter-2024-financial-results-and-announces-42-billion-capital-plan_10-30-2024"
)
STRATEGY_STRF_PRICING_URL = "https://www.strategy.com/press/strategy-announces-pricing-of-strf-perpetual-preferred-stock_03-21-2025"
STRATEGY_2030A_NOTES_URL = "https://www.strategy.com/press/microstrategy-completes-800-million-offering-of-0625-convertible-senior-notes-due-2030_03-11-2024"
STRATEGY_2031_NOTES_URL = "https://www.strategy.com/press/microstrategy-announces-pricing-of-offering-of-convertible-senior-notes_03-15-2024"
STRATEGY_2032_NOTES_URL = "https://www.strategy.com/press/microstrategy-completes-800-million-offering-of-225-convertible-senior-notes-due-2032_06-20-2024"


def _parse_number(text: str) -> float:
    match = NUMBER_PATTERN.search(text)
    if not match:
        raise ValueError(f"Unable to parse number from {text!r}")
    return float(match.group(1).replace(",", ""))


def _parse_money(text: str) -> float:
    cleaned = text.strip().replace(",", "").replace("$", "")
    suffix = cleaned[-1].upper() if cleaned else ""
    if suffix in CURRENCY_SUFFIXES:
        return float(cleaned[:-1]) * CURRENCY_SUFFIXES[suffix]
    return float(cleaned)


def _extract_from_json(obj: Any, label: str) -> str | None:
    if isinstance(obj, dict):
        lower_map = {str(key).lower(): value for key, value in obj.items()}
        for key, value in lower_map.items():
            if label in key:
                if isinstance(value, (str, int, float)):
                    return str(value)
            nested = _extract_from_json(value, label)
            if nested is not None:
                return nested
    elif isinstance(obj, list):
        for item in obj:
            nested = _extract_from_json(item, label)
            if nested is not None:
                return nested
    return None


def fetch_strategy_holdings(settings: Settings) -> HoldingsSnapshot:
    providers = (
        _fetch_holdings_from_strategy_purchases,
        _fetch_holdings_from_sec_8k,
        _fetch_holdings_from_manual_override,
    )
    errors: list[str] = []

    for provider in providers:
        try:
            return provider(settings)
        except Exception as exc:  # pragma: no cover - fallback chain
            errors.append(f"{provider.__name__}: {exc}")

    raise ValueError("Unable to resolve Strategy holdings from any provider. " + " | ".join(errors))


def _fetch_holdings_from_strategy_purchases(settings: Settings) -> HoldingsSnapshot:
    response = requests.get(
        settings.strategy_purchases_url,
        headers=_strategy_headers(settings),
        timeout=30,
    )
    response.raise_for_status()

    data = _extract_next_data_payload(response.text)
    bitcoin_data = data["props"]["pageProps"]["bitcoinData"]
    if not bitcoin_data:
        raise ValueError("Missing bitcoinData entries.")

    latest_entry = max(bitcoin_data, key=lambda item: item["date_of_purchase"])
    total_cost_usd = sum(float(item.get("total_purchase_price") or 0.0) for item in bitcoin_data)
    btc_holdings = float(latest_entry["btc_holdings"])

    if total_cost_usd <= 0 or btc_holdings <= 0:
        raise ValueError("Non-positive holdings data in purchases payload.")

    purchase_date = latest_entry["date_of_purchase"]
    return HoldingsSnapshot(
        btc_holdings=btc_holdings,
        total_cost_usd=total_cost_usd,
        source=f"Strategy purchases JSON ({purchase_date})",
    )


def _fetch_holdings_from_sec_8k(settings: Settings) -> HoldingsSnapshot:
    response = requests.get(
        SEC_SUBMISSIONS_URL,
        headers={"User-Agent": settings.sec_user_agent},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    recent = data["filings"]["recent"]

    for form, filing_date, accession_number, primary_document in zip(
        recent["form"],
        recent["filingDate"],
        recent["accessionNumber"],
        recent["primaryDocument"],
        strict=False,
    ):
        if form != "8-K":
            continue

        filing = _parse_sec_8k_holdings(settings, accession_number, primary_document)
        if filing is None:
            continue

        btc_holdings, total_cost_usd = filing
        return HoldingsSnapshot(
            btc_holdings=btc_holdings,
            total_cost_usd=total_cost_usd,
            source=f"SEC 8-K ({filing_date})",
        )

    raise ValueError("No parsable 8-K holdings filing found.")


def _parse_sec_8k_holdings(settings: Settings, accession_number: str, primary_document: str) -> tuple[float, float] | None:
    accession_no_dash = accession_number.replace("-", "")
    filing_url = f"{SEC_ARCHIVES_BASE_URL}/{accession_no_dash}/{primary_document}"
    response = requests.get(
        filing_url,
        headers={"User-Agent": settings.sec_user_agent},
        timeout=30,
    )
    response.raise_for_status()

    normalized = _normalize_html_text(response.text)
    pattern = re.compile(
        r"Aggregate Purchase Price \(in billions\)\s*\(2\)\s*Average Purchase Price \(2\)\s*"
        r"([0-9,]+)\s*\$([0-9.]+)\s*\$([0-9,]+)",
        re.IGNORECASE,
    )
    matches = pattern.findall(normalized)
    if not matches:
        return None

    btc_holdings_text, total_cost_billions_text, _average_price_text = matches[-1]
    btc_holdings = _parse_number(btc_holdings_text)
    total_cost_usd = float(total_cost_billions_text) * 1_000_000_000
    if btc_holdings <= 0 or total_cost_usd <= 0:
        return None
    return btc_holdings, total_cost_usd


def _fetch_holdings_from_manual_override(settings: Settings) -> HoldingsSnapshot:
    if settings.manual_btc_holdings and settings.manual_total_cost_usd:
        return HoldingsSnapshot(
            btc_holdings=settings.manual_btc_holdings,
            total_cost_usd=settings.manual_total_cost_usd,
            source="manual env override",
        )
    raise ValueError("Manual override values are not configured.")


def fetch_market_snapshot(settings: Settings, holdings: HoldingsSnapshot) -> MarketSnapshot:
    mstr_price = fetch_stooq_price(settings, settings.mstr_ticker)
    btc_price = fetch_coingecko_btc_price(settings)
    shares_outstanding, shares_source = fetch_shares_outstanding(settings)

    market_cap = mstr_price * shares_outstanding

    return MarketSnapshot(
        mstr_price_usd=mstr_price,
        btc_price_usd=btc_price,
        market_cap_usd=float(market_cap),
        shares_outstanding=float(shares_outstanding),
        source=f"Stooq + CoinGecko + {shares_source}",
    )


def fetch_strategy_capital_structure(settings: Settings) -> StrategyCapitalStructure:
    errors: list[str] = []

    try:
        debt_usd = _fetch_strategy_debt_notional(settings)
        preferred_stock_usd = _fetch_strategy_preferred_notional(settings)
        cash_usd = _fetch_strategy_cash_balance(settings)
        return StrategyCapitalStructure(
            debt_usd=debt_usd,
            preferred_stock_usd=preferred_stock_usd,
            cash_usd=cash_usd,
            source="official Strategy disclosures",
        )
    except Exception as exc:
        errors.append(f"automatic: {exc}")

    if (
        settings.manual_debt_usd is not None
        and settings.manual_preferred_stock_usd is not None
        and settings.manual_cash_usd is not None
    ):
        return StrategyCapitalStructure(
            debt_usd=settings.manual_debt_usd,
            preferred_stock_usd=settings.manual_preferred_stock_usd,
            cash_usd=settings.manual_cash_usd,
            source="manual env override",
        )

    raise ValueError(
        "Unable to resolve Strategy capital structure automatically and manual "
        "fallback values are not fully configured. " + " | ".join(errors)
    )


def fetch_strategy_reported_mnav(settings: Settings) -> float:
    response = requests.get(
        settings.strategy_mstr_url,
        headers=_strategy_headers(settings),
        timeout=30,
    )
    response.raise_for_status()

    page_html = response.text
    candidates: list[float] = []

    direct_match = re.search(
        r"mNAV[^0-9]{0,80}([0-9]+(?:\.[0-9]+)?)\s*x",
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    if direct_match:
        candidates.append(float(direct_match.group(1)))

    for payload in _extract_json_payloads(page_html):
        _collect_mnav_candidates(payload, candidates)

    filtered = [value for value in candidates if 0 < value < 100]
    if not filtered:
        raise ValueError("Unable to locate Strategy-reported mNAV in the MSTR page.")

    # Keep the largest candidate to avoid picking threshold values like 2.5x or 4.0x
    # when the live metric is present alongside explanatory text.
    return max(filtered)


def fetch_shares_outstanding(settings: Settings) -> tuple[float, str]:
    errors: list[str] = []

    try:
        shares_outstanding, filing_date = _fetch_shares_outstanding_from_recent_sec_filing(settings)
        return shares_outstanding, f"recent SEC filing ({filing_date})"
    except Exception as exc:
        errors.append(f"recent SEC filing: {exc}")

    if settings.manual_shares_outstanding is not None:
        return settings.manual_shares_outstanding, "manual env override"

    raise ValueError(
        "Unable to resolve shares outstanding automatically and MANUAL_SHARES_OUTSTANDING "
        "is not set. " + " | ".join(errors)
    )


def fetch_stooq_price(settings: Settings, ticker: str) -> float:
    stooq_symbol = _stooq_symbol(ticker)
    response = requests.get(
        STOOQ_QUOTE_URL,
        params={"s": stooq_symbol, "i": "1"},
        headers={"User-Agent": settings.user_agent},
        timeout=30,
    )
    response.raise_for_status()
    fields = [item.strip() for item in response.text.strip().split(",")]
    if len(fields) < 7:
        raise ValueError(f"Unexpected Stooq response for {ticker}: {response.text!r}")
    close_value = fields[6]
    if not close_value or close_value.lower() == "n/d":
        raise ValueError(f"Missing Stooq close price for {ticker}.")
    return float(close_value)


def fetch_coingecko_btc_price(settings: Settings) -> float:
    response = requests.get(
        COINGECKO_SIMPLE_PRICE_URL,
        params={"ids": "bitcoin", "vs_currencies": "usd"},
        headers={"User-Agent": settings.user_agent},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return _require_float(payload.get("bitcoin", {}).get("usd"), "BTC price")


def _stooq_symbol(ticker: str) -> str:
    if ticker.upper() == "MSTR":
        return "mstr.us"
    return quote_plus(ticker.lower())


def _require_float(value: Any, label: str) -> float:
    if value is None:
        raise ValueError(f"Missing {label}.")
    return float(value)


def _strategy_headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "X-CalmNAV-UA": settings.user_agent,
    }


def _extract_next_data_payload(page_html: str) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        page_html,
        re.DOTALL,
    )
    if not match:
        raise ValueError("Missing __NEXT_DATA__ payload.")
    return json.loads(match.group(1))


def _extract_json_payloads(page_html: str) -> list[Any]:
    payloads: list[Any] = []

    next_data_match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        page_html,
        re.DOTALL,
    )
    if next_data_match:
        payloads.append(json.loads(next_data_match.group(1)))

    for script_content in re.findall(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
        page_html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            payloads.append(json.loads(script_content))
        except json.JSONDecodeError:
            continue

    return payloads


def _collect_mnav_candidates(obj: Any, candidates: list[float]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_text = str(key).lower()
            if "mnav" in key_text:
                number = _extract_numeric_candidate(value)
                if number is not None:
                    candidates.append(number)
            _collect_mnav_candidates(value, candidates)
        return

    if isinstance(obj, list):
        for item in obj:
            _collect_mnav_candidates(item, candidates)


def _extract_numeric_candidate(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value)
        if match:
            return float(match.group(1))
    if isinstance(value, dict):
        for nested_key in ("value", "current", "amount", "displayValue", "formattedValue"):
            if nested_key in value:
                return _extract_numeric_candidate(value[nested_key])
    return None


def _normalize_html_text(page_html: str) -> str:
    text = html_lib.unescape(page_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_shares_outstanding_from_recent_sec_filing(settings: Settings) -> tuple[float, str]:
    response = requests.get(
        SEC_SUBMISSIONS_URL,
        headers={"User-Agent": settings.sec_user_agent},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    recent = data["filings"]["recent"]

    preferred_forms = ("424B5", "10-Q", "10-K", "424B3", "S-3ASR")
    for target_form in preferred_forms:
        for form, filing_date, accession_number, primary_document in zip(
            recent["form"],
            recent["filingDate"],
            recent["accessionNumber"],
            recent["primaryDocument"],
            strict=False,
        ):
            if form != target_form:
                continue

            accession_no_dash = accession_number.replace("-", "")
            filing_url = f"{SEC_ARCHIVES_BASE_URL}/{accession_no_dash}/{primary_document}"
            response = requests.get(
                filing_url,
                headers={"User-Agent": settings.sec_user_agent},
                timeout=30,
            )
            response.raise_for_status()
            normalized = _normalize_html_text(response.text)
            match = re.search(
                r"([0-9,]+)\s+shares of class a common stock outstanding as of "
                r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                normalized,
                re.IGNORECASE,
            )
            if match:
                return _parse_number(match.group(1)), match.group(2)

    raise ValueError("No recent filing disclosed basic class A shares outstanding.")


def _fetch_strategy_cash_balance(settings: Settings) -> float:
    for url in (
        STRATEGY_Q4_2025_RESULTS_URL,
        STRATEGY_Q3_2025_RESULTS_URL,
        STRATEGY_Q2_2025_RESULTS_URL,
        STRATEGY_Q1_2025_RESULTS_URL,
        STRATEGY_Q4_2024_RESULTS_URL,
    ):
        normalized = _normalize_html_text(_fetch_public_page(url, settings))
        match = re.search(
            r"Cash and Cash Equivalents:\s+As of [A-Za-z]+\s+\d{1,2},\s+\d{4},\s+"
            r"the Company had cash and cash equivalents of \$([0-9.]+)\s+(million|billion)",
            normalized,
            re.IGNORECASE,
        )
        if match:
            return _scale_number(float(match.group(1)), match.group(2))

    raise ValueError("Unable to parse cash balance from recent quarterly disclosures.")


def _fetch_strategy_preferred_notional(settings: Settings) -> float:
    q4_2024 = _normalize_html_text(_fetch_public_page(STRATEGY_Q4_2024_RESULTS_URL, settings))
    q1_2025 = _normalize_html_text(_fetch_public_page(STRATEGY_Q1_2025_RESULTS_URL, settings))
    q2_2025 = _normalize_html_text(_fetch_public_page(STRATEGY_Q2_2025_RESULTS_URL, settings))
    q3_2025 = _normalize_html_text(_fetch_public_page(STRATEGY_Q3_2025_RESULTS_URL, settings))
    q4_2025 = _normalize_html_text(_fetch_public_page(STRATEGY_Q4_2025_RESULTS_URL, settings))
    strf_ipo = _normalize_html_text(_fetch_public_page(STRATEGY_STRF_PRICING_URL, settings))

    strk_shares = sum(
        (
            _extract_required_number(
                q4_2024,
                r"issued\s+([0-9,]+)\s+shares of 8\.00% Series A Perpetual Strike Preferred Stock",
                "STRK IPO shares",
            ),
            _extract_required_number(
                q1_2025,
                r"issuance and sale of\s+([0-9,]+)\s+STRK Shares",
                "STRK Q1 ATM shares",
            ),
            _extract_required_number(
                q2_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of its 8\.00% Series A Perpetual Strike Preferred Stock",
                "STRK Q2 ATM shares",
            ),
            _extract_required_number(
                q2_2025,
                r"issuance and sale of an additional\s+([0-9,]+)\s+shares of its STRK Stock",
                "STRK July ATM shares",
            ),
            _extract_required_number(
                q3_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of its 8\.00% Series A Perpetual Strike Preferred Stock",
                "STRK Q3 ATM shares",
            ),
            _extract_required_number(
                q3_2025,
                r"issuance and sale of an additional\s+([0-9,]+)\s+shares of its STRK Stock",
                "STRK October ATM shares",
            ),
            _extract_required_number(
                q4_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of its 8\.00% Series A Perpetual Strike Preferred Stock",
                "STRK Q4 ATM shares",
            ),
            _extract_required_number(
                q4_2025,
                r"issuance and sale of an additional\s+([0-9,]+)\s+shares of its STRK Stock",
                "STRK January ATM shares",
            ),
        )
    )

    strf_shares = sum(
        (
            _extract_required_number(
                strf_ipo,
                r"pricing of its offering .*? of\s+([0-9,]+)\s+shares of 10\.00% Series A Perpetual Strife Preferred Stock",
                "STRF IPO shares",
            ),
            _extract_required_number(
                q2_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of STRF Stock under the STRF ATM Program",
                "STRF Q2 ATM shares",
            ),
            _extract_required_number(
                q2_2025,
                r"issuance and sale of an additional\s+([0-9,]+)\s+shares of STRF Stock under the STRF ATM Program",
                "STRF July ATM shares",
            ),
            _extract_required_number(
                q3_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of its 10\.00% Series A Perpetual Strife Preferred Stock",
                "STRF Q3 ATM shares",
            ),
            _extract_required_number(
                q3_2025,
                r"issuance and sale of an additional\s+([0-9,]+)\s+shares of its STRF Stock",
                "STRF October ATM shares",
            ),
            _extract_required_number(
                q4_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of its 10\.00% Series A Perpetual Strife Preferred Stock",
                "STRF Q4 ATM shares",
            ),
        )
    )

    strd_shares = sum(
        (
            _extract_required_number(
                q2_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of 10\.00% Series A Perpetual Stride Preferred Stock",
                "STRD IPO shares",
            ),
            _extract_required_number(
                q2_2025,
                r"issuance and sale of an additional\s+([0-9,]+)\s+shares of STRD Stock under the STRD ATM Program",
                "STRD July ATM shares",
            ),
            _extract_required_number(
                q3_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of its 10\.00% Series A Perpetual Stride Preferred Stock",
                "STRD Q3 ATM shares",
            ),
            _extract_required_number(
                q3_2025,
                r"issuance and sale of an additional\s+([0-9,]+)\s+shares of STRD Stock under the STRD ATM Program",
                "STRD October ATM shares",
            ),
            _extract_required_number(
                q4_2025,
                r"issuance and sale of\s+([0-9,]+)\s+shares of its 10\.00% Series A Perpetual Stride Preferred Stock",
                "STRD Q4 ATM shares",
            ),
        )
    )

    strc_stated_amount = _extract_required_money(
        q4_2025,
        r"STRC scaled to an aggregate stated amount of \$([0-9.]+)\s+(million|billion)",
        "STRC aggregate stated amount",
    )

    stre_shares = _extract_required_number(
        q4_2025,
        r"issuance and sale of\s+([0-9,]+)\s+shares of the 10\.00% Series A Perpetual Stream Preferred Stock",
        "STRE IPO shares",
    )
    stre_fx = _extract_required_float(
        q4_2025,
        r"USD/EUR exchange rate of\s+([0-9.]+)",
        "STRE FX rate",
    )

    return (
        (strk_shares + strf_shares + strd_shares) * 100.0
        + strc_stated_amount
        + stre_shares * 100.0 * stre_fx
    )


def _fetch_strategy_debt_notional(settings: Settings) -> float:
    q3_2024 = _normalize_html_text(_fetch_public_page(STRATEGY_Q3_2024_RESULTS_URL, settings))
    q4_2024 = _normalize_html_text(_fetch_public_page(STRATEGY_Q4_2024_RESULTS_URL, settings))
    q1_2025 = _normalize_html_text(_fetch_public_page(STRATEGY_Q1_2025_RESULTS_URL, settings))
    note_2030a = _normalize_html_text(_fetch_public_page(STRATEGY_2030A_NOTES_URL, settings))
    note_2031 = _normalize_html_text(_fetch_public_page(STRATEGY_2031_NOTES_URL, settings))
    note_2032 = _normalize_html_text(_fetch_public_page(STRATEGY_2032_NOTES_URL, settings))

    amounts = (
        _extract_required_money(
            note_2030a,
            r"aggregate principal amount of the notes sold in the offering was \$([0-9.]+)\s+(million|billion)",
            "2030A notes",
        ),
        _extract_required_money(
            note_2031,
            r"pricing of its offering of \$([0-9.]+)\s+(million|billion)\s+aggregate principal amount of 0\.875% convertible senior notes due 2031",
            "2031 notes",
        ),
        _extract_required_money(
            note_2032,
            r"aggregate principal amount of the notes sold in the offering was \$([0-9.]+)\s+(million|billion)",
            "2032 notes",
        ),
        _extract_required_money(
            q3_2024,
            r"Issuance of 2028 Convertible Notes:\s+In September 2024,\s+the Company issued \$([0-9.]+)\s+(million|billion)\s+aggregate principal amount of 0\.625% Convertible Senior Notes due 2028",
            "2028 notes",
        ),
        _extract_required_money(
            q4_2024,
            r"Issuance of 2029 Convertible Notes:\s+In November 2024,\s+the Company issued \$([0-9.]+)\s+(million|billion)\s+aggregate principal amount of 0% Convertible Senior Notes due 2029",
            "2029 notes",
        ),
        _extract_required_money(
            q1_2025,
            r"Issuance of 2030B Convertible Notes:\s+In February 2025,\s+the Company issued \$([0-9.]+)\s+(million|billion)\s+in 0% Convertible Senior Notes due 2030",
            "2030B notes",
        ),
    )

    return sum(amounts)


def _fetch_public_page(url: str, settings: Settings) -> str:
    headers = {"User-Agent": settings.sec_user_agent} if "sec.gov" in url else _strategy_headers(settings)
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def _extract_required_number(text: str, pattern: str, label: str) -> float:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"Missing {label}.")
    return _parse_number(match.group(1))


def _extract_required_float(text: str, pattern: str, label: str) -> float:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"Missing {label}.")
    return float(match.group(1))


def _extract_required_money(text: str, pattern: str, label: str) -> float:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"Missing {label}.")
    return _scale_number(float(match.group(1)), match.group(2))


def _scale_number(value: float, unit: str) -> float:
    normalized = unit.strip().lower()
    if normalized == "million":
        return value * 1_000_000
    if normalized == "billion":
        return value * 1_000_000_000
    raise ValueError(f"Unsupported unit: {unit!r}")
