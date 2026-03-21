from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from calmnav.calculator import StrategyDefinedMNavResult, compute_mnav, compute_strategy_defined_mnav
from calmnav.config import settings
from calmnav.data_sources import (
    fetch_market_snapshot,
    fetch_strategy_capital_structure,
    fetch_strategy_holdings,
    fetch_strategy_reported_mnav,
)
from calmnav.notifier import build_discord_payload, format_message, post_to_discord
from calmnav.schedule_state import mark_slot_sent, should_send_slot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute MSTR mNAV and optionally post to Discord.")
    parser.add_argument(
        "--send-discord",
        action="store_true",
        help="Send the result to DISCORD_WEBHOOK_URL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a formatted message.",
    )
    parser.add_argument(
        "--scheduled-run",
        action="store_true",
        help="Only send output when the current local alert time matches a configured alert window.",
    )
    return parser


def get_current_alert_slot() -> str | None:
    alert_tz = ZoneInfo(settings.alert_timezone)
    now_local = datetime.now(alert_tz)
    current_minutes = now_local.hour * 60 + now_local.minute

    for alert_time in settings.alert_times:
        hour_text, minute_text = alert_time.split(":", 1)
        target_minutes = int(hour_text) * 60 + int(minute_text)
        delta = current_minutes - target_minutes
        if 0 <= delta <= settings.alert_window_minutes:
            return f"{now_local.date().isoformat()}-{alert_time}"

    return None


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    slot_key: str | None = None
    if args.scheduled_run:
        slot_key = get_current_alert_slot()
        if not slot_key:
            print("Skipping run outside target alert window.")
            return 0

        decision = should_send_slot(settings, slot_key)
        print(decision.reason)
        if not decision.should_send:
            return 0

    holdings = fetch_strategy_holdings(settings)
    market = fetch_market_snapshot(settings, holdings)
    result = compute_mnav(holdings, market)
    strategy_defined_result: StrategyDefinedMNavResult | None = None
    strategy_defined_source: str | None = None
    strategy_defined_error: str | None = None
    strategy_reported_mnav: float | None = None
    strategy_reported_error: str | None = None

    try:
        capital_structure = fetch_strategy_capital_structure(settings)
        strategy_defined_result = compute_strategy_defined_mnav(holdings, market, capital_structure)
        strategy_defined_source = capital_structure.source
    except Exception as exc:
        strategy_defined_error = str(exc)

    try:
        strategy_reported_mnav = fetch_strategy_reported_mnav(settings)
    except Exception as exc:
        strategy_reported_error = str(exc)

    payload = {
        "mstr_price_usd": market.mstr_price_usd,
        "btc_price_usd": market.btc_price_usd,
        "market_cap_usd": market.market_cap_usd,
        "shares_outstanding": market.shares_outstanding,
        "btc_holdings": holdings.btc_holdings,
        "total_cost_usd": holdings.total_cost_usd,
        "btc_market_value_usd": result.btc_market_value_usd,
        "simple_mnav": result.mnav,
        "strategy_defined_mnav": strategy_defined_result.mnav if strategy_defined_result is not None else None,
        "strategy_reported_mnav": strategy_reported_mnav,
        "strategy_enterprise_value_usd": (
            strategy_defined_result.enterprise_value_usd if strategy_defined_result is not None else None
        ),
        "strategy_bitcoin_nav_usd": (
            strategy_defined_result.bitcoin_nav_usd if strategy_defined_result is not None else None
        ),
        "premium_to_cost": result.premium_to_cost,
        "holdings_source": holdings.source,
        "market_source": market.source,
        "strategy_defined_source": strategy_defined_source,
        "strategy_defined_error": strategy_defined_error,
        "strategy_reported_error": strategy_reported_error,
    }

    content = (
        json.dumps(payload, indent=2)
        if args.json
        else format_message(holdings, market, result, strategy_defined_result, strategy_reported_mnav)
    )
    print(content)

    if args.send_discord:
        if not settings.discord_webhook_url:
            parser.error("DISCORD_WEBHOOK_URL must be set when using --send-discord.")
        post_to_discord(
            settings.discord_webhook_url,
            build_discord_payload(
                settings,
                holdings,
                market,
                result,
                strategy_defined_result,
                strategy_reported_mnav,
            ),
        )
        if args.scheduled_run and slot_key:
            mark_slot_sent(settings, slot_key)

    return 0


if __name__ == "__main__":
    sys.exit(main())
