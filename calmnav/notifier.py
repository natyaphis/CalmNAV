from __future__ import annotations

from datetime import datetime, timezone

import requests

from calmnav.calculator import HoldingsSnapshot, MNavResult, MarketSnapshot


def format_message(
    holdings: HoldingsSnapshot,
    market: MarketSnapshot,
    result: MNavResult,
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "\n".join(
        [
            f"CalmNAV update ({timestamp})",
            f"MSTR price: ${market.mstr_price_usd:,.2f}",
            f"BTC price: ${market.btc_price_usd:,.2f}",
            f"MSTR market cap: ${market.market_cap_usd / 1_000_000_000:,.2f}B",
            f"Reported BTC: {holdings.btc_holdings:,.0f}",
            f"Total cost: ${holdings.total_cost_usd / 1_000_000_000:,.2f}B",
            f"BTC market value: ${result.btc_market_value_usd / 1_000_000_000:,.2f}B",
            f"mNAV: {result.mnav:.3f}x",
            f"Premium to cost: {result.premium_to_cost:.3f}x",
            f"Data sources: holdings={holdings.source}; market={market.source}",
        ]
    )


def post_to_discord(webhook_url: str, content: str) -> None:
    response = requests.post(webhook_url, json={"content": content}, timeout=30)
    response.raise_for_status()
