# Changelog

All notable changes to QuantX are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and project versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) where applicable.

This changelog starts tracking the current development line; it is not a complete reconstruction of all historical repository changes.

## [Unreleased]

### Added

- Explicit market-module architecture with India as the only implemented market and digital assets represented by an unimplemented placeholder.
- A credential-free, deterministic local paper-execution smoke example.

### Notes

- No additional market implementation, FX/multi-currency support, or new LIVE venue is implied by the market-module architecture.
- Historical implementation and validation records remain in `docs/STATUS.md` until the planned status/history documentation split is completed.
