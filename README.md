# QuantX

Open-source, modular, event-driven trading infrastructure and platform for Indian markets.

## Status

Architecture and research phase. No production trading implementation has been committed yet.

## Design direction

QuantX is being designed as a modular monolith first, with a distributed-ready architecture. The core is event-driven and domain-driven, with ports-and-adapters, capability-based broker/data integrations, and a plugin-first ecosystem.

The initial product focus is Indian markets, including equities, futures and options, while keeping the universal trading core market-neutral enough to support additional venues later.

## Current planning baseline

- QuantumTrade v1.6: engineering reference for event-driven trading, execution, safety and session/API design.
- OpenAlgo: Indian broker/platform and control-plane reference.
- Hummingbot: connector and plugin architecture reference.
- NautilusTrader: event-driven, deterministic and adapter-oriented architecture reference.
- Freqtrade, Jesse, LEAN and vectorbt: strategy and research workflow references.

## Planned architectural principles

1. Modular monolith first; distributed-ready later.
2. Minimal, stable core with plugins and adapters around it.
3. Event-driven trading lifecycle.
4. Domain-driven contracts for orders, fills, positions, portfolios, risk and execution.
5. Broker and market-data integrations are adapters, not core dependencies.
6. Capability-based compatibility checks.
7. Backtest, sandbox, paper and live share the same trading semantics.
8. F&O is represented in the domain model from the beginning.
9. UI and AI consume the engine through stable APIs instead of defining the core.
10. Local-first deployment with optional distributed operation.

## Roadmap

The project is following a research → compare → decide → document → build process. Detailed architecture and roadmap documents will be added on the architecture branch before implementation begins.
