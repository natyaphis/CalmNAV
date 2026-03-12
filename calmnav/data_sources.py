from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any
from urllib.parse import quote_plus

import requests

from calmnav.calculator import HoldingsSnapshot, MarketSnapshot
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

    shares_outstanding = settings.manual_shares_outstanding
    if shares_outstanding is None:
        raise ValueError("MANUAL_SHARES_OUTSTANDING must be set for market-cap calculation.")

    market_cap = mstr_price * shares_outstanding

    return MarketSnapshot(
        mstr_price_usd=mstr_price,
        btc_price_usd=btc_price,
        market_cap_usd=float(market_cap),
        shares_outstanding=float(shares_outstanding),
        source="Stooq + CoinGecko",
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


def _normalize_html_text(page_html: str) -> str:
    text = html_lib.unescape(page_html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
