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
                "title": "CALMNAV TERMINAL",
                "color": settings.discord_embed_color,
                "description": (
                    "```text\n"
                    f"MSTR {market.mstr_price_usd:>10,.2f} USD\n"
                    f"BTC  {market.btc_price_usd:>10,.2f} USD\n"
                    f"mNAV {result.mnav:>10.3f} x\n"
                    "```"
                ),
                "timestamp": timestamp,
                "fields": [
                    {
                        "name": "BALANCE SHEET",
                        "value": (
                            "```text\n"
                            f"BTC HELD   {holdings.btc_holdings:>12,.0f}\n"
                            f"BTC VALUE  {result.btc_market_value_usd / 1_000_000_000:>12,.2f}B\n"
                            f"COST BASIS {holdings.total_cost_usd / 1_000_000_000:>12,.2f}B\n"
                            f"MKT CAP    {market.market_cap_usd / 1_000_000_000:>12,.2f}B\n"
                            "```"
                        ),
                        "inline": True,
                    },
                    {
                        "name": "RATIOS",
                        "value": (
                            "```text\n"
                            f"MNAV       {result.mnav:>12.3f}x\n"
                            f"PREM/COST  {result.premium_to_cost:>12.3f}x\n"
                            f"SHARES OS  {market.shares_outstanding / 1_000_000:>10.2f}M\n"
                            "```"
                        ),
                        "inline": True,
                    },
                    {
                        "name": "FEEDS",
                        "value": (
                            "```text\n"
                            f"HOLDINGS {holdings.source}\n"
                            f"MARKET   {market.source}\n"
                            "```"
                        ),
                        "inline": False,
                    },
                ],
                "footer": {"text": "Sydney schedule 09:00 / 21:00"},
            }
        ]
    }


def post_to_discord(webhook_url: str, payload: dict) -> None:
    response = requests.post(webhook_url, json=payload, timeout=30)
    response.raise_for_status()
