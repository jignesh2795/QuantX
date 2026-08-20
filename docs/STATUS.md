# QuantX Planning Status

**Status:** Architecture and research phase.

## Current baseline

- Repository initialized with a minimal documentation baseline.
- No production trading implementation has been started in QuantX.
- QuantumTrade v1.6 is the principal engineering reference.
- OpenAlgo, Hummingbot, NautilusTrader, Freqtrade, Jesse, LEAN and vectorbt are research references.

## Current architecture direction

QuantX is planned as a modular monolith first, with a distributed-ready design:

- event-driven domain core
- domain-driven contracts
- ports and adapters
- capability-based integrations
- plugin-first extensibility
- data/control/execution plane separation
- common semantics across backtest, sandbox, paper and live
- Indian-market and F&O-first domain model
- local-first deployment

## Immediate next step

Create and populate the `docs/architecture-roadmap` branch with the architecture specification, ADRs and consolidated roadmap before production implementation.
