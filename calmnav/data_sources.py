from __future__ import annotations

import json
import re
from typing import Any

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
    if settings.manual_btc_holdings and settings.manual_total_cost_usd:
        return HoldingsSnapshot(
            btc_holdings=settings.manual_btc_holdings,
            total_cost_usd=settings.manual_total_cost_usd,
            source="manual env override",
        )

    response = requests.get(
        settings.strategy_purchases_url,
        headers={"User-Agent": settings.user_agent},
        timeout=30,
    )
    response.raise_for_status()
    html = response.text

    btc_holdings = _extract_metric_from_html(
        html,
        labels=("reported btc", "bitcoin holdings", "btc holdings"),
        money=False,
    )
    total_cost_usd = _extract_metric_from_html(
        html,
        labels=("total cost", "aggregate cost", "cost basis"),
        money=True,
    )

    return HoldingsSnapshot(
        btc_holdings=btc_holdings,
        total_cost_usd=total_cost_usd,
        source=settings.strategy_purchases_url,
    )


def _extract_metric_from_html(html: str, labels: tuple[str, ...], money: bool) -> float:
    lowered = html.lower()

    for label in labels:
        if label not in lowered:
            continue

        direct_match = re.search(
            rf"{re.escape(label)}[\s\S]{{0,200}}?(\$?[0-9][0-9,]*(?:\.[0-9]+)?[kmbt]?)",
            lowered,
            re.IGNORECASE,
        )
        if direct_match:
            value = direct_match.group(1)
            return _parse_money(value) if money else _parse_number(value)

    json_blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    for block in json_blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        for label in labels:
            value = _extract_from_json(payload, label)
            if value is not None:
                return _parse_money(value) if money else _parse_number(value)

    raise ValueError(f"Unable to find labels {labels!r} in Strategy purchases page.")


def fetch_market_snapshot(settings: Settings, holdings: HoldingsSnapshot) -> MarketSnapshot:
    import yfinance as yf

    mstr = yf.Ticker(settings.mstr_ticker)
    btc = yf.Ticker(settings.btc_ticker)

    mstr_fast = mstr.fast_info
    btc_fast = btc.fast_info

    mstr_price = _require_float(mstr_fast.get("lastPrice"), "MSTR last price")
    btc_price = _require_float(btc_fast.get("lastPrice"), "BTC last price")

    shares_outstanding = settings.manual_shares_outstanding
    if shares_outstanding is None:
        shares_outstanding = _resolve_shares_outstanding(mstr)

    market_cap = mstr_fast.get("marketCap")
    if market_cap is None:
        market_cap = mstr_price * shares_outstanding

    return MarketSnapshot(
        mstr_price_usd=mstr_price,
        btc_price_usd=btc_price,
        market_cap_usd=float(market_cap),
        shares_outstanding=float(shares_outstanding),
        source="yfinance",
    )


def _resolve_shares_outstanding(ticker: Any) -> float:
    fast_info = ticker.fast_info
    shares = fast_info.get("shares")
    if shares:
        return float(shares)

    info = ticker.info
    for key in ("sharesOutstanding", "impliedSharesOutstanding"):
        value = info.get(key)
        if value:
            return float(value)

    raise ValueError("Unable to resolve MSTR shares outstanding.")


def _require_float(value: Any, label: str) -> float:
    if value is None:
        raise ValueError(f"Missing {label}.")
    return float(value)
