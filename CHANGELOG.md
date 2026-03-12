# Changelog

All notable changes to this project will be documented in this file.

## [1.0.2] - 2026-03-12

### Changed

- Added fallback scheduled runs for each Sydney alert slot.
- Added GitHub-backed sent-slot state to prevent duplicate Discord notifications between primary and fallback runs.
- Hardened the 09:00 and 21:00 Sydney delivery flow against missed GitHub scheduled executions.

## [1.0.1] - 2026-03-12

### Changed

- Added Discord embed-based notifications with configurable accent color.
- Restyled the Discord message into a more terminal-like financial card layout.
- Emphasized top-line quote data and mNAV in the Discord notification format.
- Updated the GitHub release workflow skill to support non-`.toc` projects such as CalmNAV.
- Added a project screenshot asset and embedded it in the README.

## [1.0.0] - 2026-03-12

### Added

- Initial `CalmNAV` CLI for calculating a simple MSTR mNAV ratio.
- Discord webhook notification support.
- GitHub Actions workflow for scheduled and manual notification runs.
- Sydney-local alert scheduling at `09:00` and `21:00`.
- Manual fallback configuration for BTC holdings, total cost, and shares outstanding.

### Changed

- Switched market data fetching to Stooq for `MSTR` and CoinGecko for `BTC`.
- Updated workflow behavior so manual `workflow_dispatch` runs send immediately.
- Added a formal holdings fallback chain: Strategy purchases JSON, then SEC 8-K, then manual overrides.

### Notes

- Holdings automation now prefers official Strategy purchases JSON and falls back to official SEC 8-K data before using manual secrets.
- The current metric is a simple market-cap-based mNAV, not Strategy's full enterprise-value-based definition.
