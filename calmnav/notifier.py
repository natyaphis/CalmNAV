from __future__ import annotations

from datetime import datetime, timezone

import requests

from calmnav.calculator import HoldingsSnapshot, MNavResult, MarketSnapshot
from calmnav.config import Settings


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


def build_discord_payload(
    settings: Settings,
    holdings: HoldingsSnapshot,
    market: MarketSnapshot,
    result: MNavResult,
) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "embeds": [
            {
                "title": "CalmNAV Update",
                "color": settings.discord_embed_color,
                "description": (
                    f"**mNAV {result.mnav:.3f}x**\n"
                    f"MSTR `${market.mstr_price_usd:,.2f}` | "
                    f"BTC `${market.btc_price_usd:,.2f}`"
                ),
                "timestamp": timestamp,
                "fields": [
                    {"name": "Premium to Cost", "value": f"{result.premium_to_cost:.3f}x", "inline": True},
                    {"name": "Reported BTC", "value": f"{holdings.btc_holdings:,.0f}", "inline": True},
                    {"name": "Total Cost", "value": f"${holdings.total_cost_usd / 1_000_000_000:,.2f}B", "inline": True},
                    {"name": "BTC Market Value", "value": f"${result.btc_market_value_usd / 1_000_000_000:,.2f}B", "inline": True},
                    {"name": "MSTR Market Cap", "value": f"${market.market_cap_usd / 1_000_000_000:,.2f}B", "inline": True},
                    {"name": "Sources", "value": f"holdings={holdings.source}\nmarket={market.source}", "inline": False},
                ],
            }
        ]
    }


def post_to_discord(webhook_url: str, payload: dict) -> None:
    response = requests.post(webhook_url, json=payload, timeout=30)
    response.raise_for_status()
