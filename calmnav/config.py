from __future__ import annotations

import os
from dataclasses import dataclass


def _read_float(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    return float(value.replace(",", "").strip())


@dataclass(frozen=True)
class Settings:
    strategy_purchases_url: str = os.getenv(
        "STRATEGY_PURCHASES_URL",
        "https://www.strategy.com/purchases",
    )
    mstr_ticker: str = os.getenv("MSTR_TICKER", "MSTR")
    btc_ticker: str = os.getenv("BTC_TICKER", "BTC-USD")
    discord_webhook_url: str | None = os.getenv("DISCORD_WEBHOOK_URL")
    user_agent: str = os.getenv(
        "CALMNAV_USER_AGENT",
        "CalmNAV/0.1 (+https://github.com/your-org/CalmNAV)",
    )
    manual_btc_holdings: float | None = _read_float("MANUAL_BTC_HOLDINGS")
    manual_total_cost_usd: float | None = _read_float("MANUAL_TOTAL_COST_USD")
    manual_shares_outstanding: float | None = _read_float("MANUAL_SHARES_OUTSTANDING")


settings = Settings()
