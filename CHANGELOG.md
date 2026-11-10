# Changelog

All notable changes to QuantX are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The package version is recorded in `pyproject.toml`.

This changelog starts tracking the current development line; it is not a complete reconstruction of all historical repository changes.

## [0.1.0.dev0] - Unreleased

### Added

- Explicit market-module architecture with India as the only implemented market and digital assets represented by an unimplemented placeholder.
- A credential-free, deterministic local paper-execution smoke example.

### Notes

- No additional market implementation, FX/multi-currency support, or new LIVE venue is implied by the market-module architecture.
- Historical implementation and validation records are preserved in [`docs/STATUS_HISTORY.md`](docs/STATUS_HISTORY.md); [`docs/STATUS.md`](docs/STATUS.md) is the concise current-state snapshot.
