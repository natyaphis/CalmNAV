from __future__ import annotations

import os
from dataclasses import dataclass


def _read_float(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    return float(value.replace(",", "").strip())


def _read_csv(name: str, default: str) -> tuple[str, ...]:
    value = os.getenv(name, default)
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _read_embed_color(name: str, default: str) -> int:
    value = os.getenv(name, default).strip().lower()
    if value.startswith("#"):
        value = value[1:]
    if value.startswith("0x"):
        value = value[2:]
    return int(value, 16)


@dataclass(frozen=True)
class Settings:
    strategy_purchases_url: str = os.getenv(
        "STRATEGY_PURCHASES_URL",
        "https://www.strategy.com/purchases",
    )
    mstr_ticker: str = os.getenv("MSTR_TICKER", "MSTR")
    btc_ticker: str = os.getenv("BTC_TICKER", "BTC-USD")
    discord_webhook_url: str | None = os.getenv("DISCORD_WEBHOOK_URL")
    discord_embed_color: int = _read_embed_color("DISCORD_EMBED_COLOR", "FA660F")
    user_agent: str = os.getenv(
        "CALMNAV_USER_AGENT",
        "CalmNAV/0.1 (+https://github.com/your-org/CalmNAV)",
    )
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "CalmNAV/1.0.1 (https://github.com/natyaphis/CalmNAV; contact via GitHub)",
    )
    alert_timezone: str = os.getenv("ALERT_TIMEZONE", "Australia/Sydney")
    alert_times: tuple[str, ...] = _read_csv("ALERT_TIMES", "09:00,21:00")
    manual_btc_holdings: float | None = _read_float("MANUAL_BTC_HOLDINGS")
    manual_total_cost_usd: float | None = _read_float("MANUAL_TOTAL_COST_USD")
    manual_shares_outstanding: float | None = _read_float("MANUAL_SHARES_OUTSTANDING")


settings = Settings()
