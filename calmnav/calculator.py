from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HoldingsSnapshot:
    btc_holdings: float
    total_cost_usd: float
    source: str


@dataclass(frozen=True)
class MarketSnapshot:
    mstr_price_usd: float
    btc_price_usd: float
    market_cap_usd: float
    shares_outstanding: float
    source: str


@dataclass(frozen=True)
class MNavResult:
    mnav: float
    btc_market_value_usd: float
    premium_to_cost: float


def compute_mnav(holdings: HoldingsSnapshot, market: MarketSnapshot) -> MNavResult:
    btc_market_value_usd = holdings.btc_holdings * market.btc_price_usd
    if btc_market_value_usd <= 0:
        raise ValueError("BTC market value must be positive.")
    if holdings.total_cost_usd <= 0:
        raise ValueError("Total cost must be positive.")

    mnav = market.market_cap_usd / btc_market_value_usd
    premium_to_cost = market.market_cap_usd / holdings.total_cost_usd

    return MNavResult(
        mnav=mnav,
        btc_market_value_usd=btc_market_value_usd,
        premium_to_cost=premium_to_cost,
    )
