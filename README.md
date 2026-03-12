# CalmNAV

Lightweight MSTR mNAV calculator with optional Discord notifications.

Current version: `1.0.1`

## What it does

- Pulls Strategy BTC holdings and total cost with a fallback chain:
  - `https://www.strategy.com/purchases` structured `__NEXT_DATA__`
  - latest official Strategy `8-K` from SEC
  - manual override secrets
- Fetches `MSTR` price from Stooq and `BTC` price from CoinGecko.
- Computes a simple mNAV ratio as:

```text
mNAV = MSTR market cap / (reported BTC holdings * BTC price)
```

- Posts the result to a Discord channel through a webhook.
- Can run locally or on a GitHub Actions schedule.

## Local usage

1. Create a virtual environment and install dependencies.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment variables.

```bash
cp .env.example .env
```

Set these values as needed:

- `DISCORD_WEBHOOK_URL`: required only when sending to Discord
- `DISCORD_EMBED_COLOR`: optional hex embed color, defaults to `FA660F`
- `ALERT_TIMEZONE`: optional, defaults to `Australia/Sydney`
- `ALERT_TIMES`: optional comma-separated 24-hour times, defaults to `09:00,21:00`
- `SEC_USER_AGENT`: optional but recommended for SEC requests
- `MANUAL_BTC_HOLDINGS`: optional fallback if the Strategy page changes
- `MANUAL_TOTAL_COST_USD`: optional fallback if the Strategy page changes
- `MANUAL_SHARES_OUTSTANDING`: required for market-cap calculation in the current GitHub Actions setup

3. Run the calculator.

```bash
python3 -m calmnav.main
python3 -m calmnav.main --json
python3 -m calmnav.main --send-discord
```

## GitHub Actions setup

Add these repository secrets:

- `DISCORD_WEBHOOK_URL`
- `DISCORD_EMBED_COLOR` (optional)
- `SEC_USER_AGENT` (optional, recommended)
- `MANUAL_BTC_HOLDINGS` (optional)
- `MANUAL_TOTAL_COST_USD` (optional)
- `MANUAL_SHARES_OUTSTANDING` (optional)

The included workflow runs every day at these UTC slots:

- `22:00 UTC`
- `23:00 UTC`
- `10:00 UTC`
- `11:00 UTC`

The script uses the configured local alert timezone and only sends messages at:

- `09:00 Australia/Sydney`
- `21:00 Australia/Sydney`

The extra UTC entries are there to cover both AEST and AEDT. GitHub Actions can still run late, so timing is best-effort rather than exact-to-the-minute.

Manual `workflow_dispatch` runs bypass the schedule guard and send immediately, which is useful for testing the Discord notification path.

## Notes

- The primary holdings source is the Strategy purchases page's structured Next.js payload. If that fails, CalmNAV falls back to the latest official Strategy `8-K`, then to manual secrets.
- Stooq and CoinGecko are convenient for a first version but are not official low-latency market data feeds.
- This project currently computes a simple market-cap-based mNAV, not Strategy's full enterprise-value-based definition.
