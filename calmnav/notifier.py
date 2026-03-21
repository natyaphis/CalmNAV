from __future__ import annotations

from datetime import datetime, timezone

import requests

from calmnav.calculator import HoldingsSnapshot, MNavResult, MarketSnapshot, StrategyDefinedMNavResult
from calmnav.config import Settings


def format_message(
    holdings: HoldingsSnapshot,
    market: MarketSnapshot,
    result: MNavResult,
    strategy_defined_result: StrategyDefinedMNavResult | None = None,
    strategy_reported_mnav: float | None = None,
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    strategy_defined_text = (
        f"Strategy-defined mNAV: {strategy_defined_result.mnav:.3f}x"
        if strategy_defined_result is not None
        else "Strategy-defined mNAV: unavailable"
    )
    strategy_reported_text = (
        f"Strategy-reported mNAV: {strategy_reported_mnav:.3f}x"
        if strategy_reported_mnav is not None
        else "Strategy-reported mNAV: unavailable"
    )
    return "\n".join(
        [
            f"CalmNAV update ({timestamp})",
            f"MSTR price: ${market.mstr_price_usd:,.2f}",
            f"BTC price: ${market.btc_price_usd:,.2f}",
            f"MSTR market cap: ${market.market_cap_usd / 1_000_000_000:,.2f}B",
            f"Reported BTC: {holdings.btc_holdings:,.0f}",
            f"Total cost: ${holdings.total_cost_usd / 1_000_000_000:,.2f}B",
            f"BTC market value: ${result.btc_market_value_usd / 1_000_000_000:,.2f}B",
            f"Simple mNAV: {result.mnav:.3f}x",
            strategy_defined_text,
            strategy_reported_text,
            f"Premium to cost: {result.premium_to_cost:.3f}x",
            f"Data sources: holdings={holdings.source}; market={market.source}",
        ]
    )


def build_discord_payload(
    settings: Settings,
    holdings: HoldingsSnapshot,
    market: MarketSnapshot,
    result: MNavResult,
    strategy_defined_result: StrategyDefinedMNavResult | None = None,
    strategy_reported_mnav: float | None = None,
) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    ratios_lines = [f"SIMPLE     {result.mnav:>12.3f}x"]
    if strategy_defined_result is not None:
        ratios_lines.append(f"STRATEGY   {strategy_defined_result.mnav:>12.3f}x")
    if strategy_reported_mnav is not None:
        ratios_lines.append(f"WEB        {strategy_reported_mnav:>12.3f}x")
    ratios_lines.extend(
        [
            f"PREM/COST  {result.premium_to_cost:>12.3f}x",
            f"SHARES OS  {market.shares_outstanding / 1_000_000:>10.2f}M",
        ]
    )
    strategy_defined_line = (
        f"DEF  {strategy_defined_result.mnav:>10.3f} x\n"
        if strategy_defined_result is not None
        else ""
    )
    strategy_reported_line = (
        f"WEB  {strategy_reported_mnav:>10.3f} x\n"
        if strategy_reported_mnav is not None
        else ""
    )
    return {
        "embeds": [
            {
                "title": "CALMNAV TERMINAL",
                "color": settings.discord_embed_color,
                "description": (
                    "```text\n"
                    f"MSTR {market.mstr_price_usd:>10,.2f} USD\n"
                    f"BTC  {market.btc_price_usd:>10,.2f} USD\n"
                    f"SIMP {result.mnav:>10.3f} x\n"
                    f"{strategy_defined_line}"
                    f"{strategy_reported_line}"
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
                        "value": "```text\n" + "\n".join(ratios_lines) + "\n```",
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
