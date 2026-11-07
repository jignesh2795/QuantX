# QuantX Research Notes

This directory records comparative research used to make architecture decisions.

## Pinned architecture comparison

- [Global Trading Architecture Comparison — 2026-11-07](./2026-11-global-architecture-comparison.md) — source-backed review of pinned LEAN, NautilusTrader, Hummingbot, OpenAlgo, CCXT and Indian broker SDK revisions. Recommends the bounded M4.5 Flow-to-existing-runtime parity slice; does not authorize additional markets or LIVE changes.

Current reference families:

- QuantumTrade v1.6 — event-driven trading core, safety, execution, session/API design
- OpenAlgo — Indian broker/platform and control-plane features
- Hummingbot — connector and plugin architecture
- NautilusTrader — event-driven, deterministic and adapter-oriented trading architecture
- Freqtrade — open-source strategy/backtest/dry-run workflow
- Jesse — research and benchmarking workflow
- LEAN — research-to-live lifecycle
- vectorbt — vectorized research acceleration
- Indian-market F&O requirements — contracts, expiry, strikes, Greeks, margin and execution realities

The objective is to reuse or integrate proven ideas instead of reproducing existing projects unnecessarily.
