from __future__ import annotations

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
    lines = [line.strip() for line in response.text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError(f"Unexpected Stooq response for {ticker}: {response.text!r}")
    header = [item.strip().lower() for item in lines[0].split(",")]
    values = [item.strip() for item in lines[1].split(",")]
    row = dict(zip(header, values, strict=False))
    close_value = row.get("close")
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
