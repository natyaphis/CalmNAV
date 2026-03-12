# CalmNAV

Lightweight MSTR mNAV calculator with optional Discord notifications.

## What it does

- Scrapes `https://www.strategy.com/purchases` for Strategy's reported BTC holdings and total cost.
- Fetches `MSTR` and `BTC-USD` market data from the Yahoo Finance quote endpoint.
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
- `MANUAL_BTC_HOLDINGS`: optional fallback if the Strategy page changes
- `MANUAL_TOTAL_COST_USD`: optional fallback if the Strategy page changes
- `MANUAL_SHARES_OUTSTANDING`: optional override if Yahoo Finance does not return enough market-cap data

3. Run the calculator.

```bash
python3 -m calmnav.main
python3 -m calmnav.main --json
python3 -m calmnav.main --send-discord
```

## GitHub Actions setup

Add these repository secrets:

- `DISCORD_WEBHOOK_URL`
- `MANUAL_BTC_HOLDINGS` (optional)
- `MANUAL_TOTAL_COST_USD` (optional)
- `MANUAL_SHARES_OUTSTANDING` (optional)

The included workflow runs on weekdays at:

- `12:30 UTC`
- `14:30 UTC`
- `21:00 UTC`
- `22:00 UTC`

The script uses New York time and the NYSE calendar to only send messages at:

- `08:30 America/New_York`
- `17:00 America/New_York`

The extra UTC entries are there to cover both EST and EDT. GitHub Actions can still run late, so timing is best-effort rather than exact-to-the-minute.

Manual `workflow_dispatch` runs bypass the schedule guard and send immediately, which is useful for testing the Discord notification path.

## Notes

- The Strategy purchases page is a website, not a guaranteed public API. Expect scraping breakage eventually.
- The Yahoo Finance quote endpoint is convenient for a first version but is not an official low-latency market data feed.
- This project currently computes a simple market-cap-based mNAV, not Strategy's full enterprise-value-based definition.
