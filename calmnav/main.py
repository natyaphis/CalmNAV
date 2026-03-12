from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from calmnav.calculator import compute_mnav
from calmnav.config import settings
from calmnav.data_sources import fetch_market_snapshot, fetch_strategy_holdings
from calmnav.notifier import format_message, post_to_discord


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
        help="Only send output when the current New York time matches an alert window on a NYSE trading day.",
    )
    return parser


def should_run_now() -> bool:
    import pandas_market_calendars as mcal

    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(ny_tz)
    allowed_times = {(8, 30), (17, 0)}
    if (now_ny.hour, now_ny.minute) not in allowed_times:
        return False

    nyse = mcal.get_calendar("NYSE")
    schedule = nyse.schedule(start_date=now_ny.date(), end_date=now_ny.date())
    return not schedule.empty


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.scheduled_run and not should_run_now():
        print("Skipping run outside target NYSE alert window.")
        return 0

    holdings = fetch_strategy_holdings(settings)
    market = fetch_market_snapshot(settings, holdings)
    result = compute_mnav(holdings, market)

    payload = {
        "mstr_price_usd": market.mstr_price_usd,
        "btc_price_usd": market.btc_price_usd,
        "market_cap_usd": market.market_cap_usd,
        "shares_outstanding": market.shares_outstanding,
        "btc_holdings": holdings.btc_holdings,
        "total_cost_usd": holdings.total_cost_usd,
        "btc_market_value_usd": result.btc_market_value_usd,
        "mnav": result.mnav,
        "premium_to_cost": result.premium_to_cost,
        "holdings_source": holdings.source,
        "market_source": market.source,
    }

    content = json.dumps(payload, indent=2) if args.json else format_message(holdings, market, result)
    print(content)

    if args.send_discord:
        if not settings.discord_webhook_url:
            parser.error("DISCORD_WEBHOOK_URL must be set when using --send-discord.")
        post_to_discord(settings.discord_webhook_url, format_message(holdings, market, result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
