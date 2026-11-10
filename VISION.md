# QuantX Vision

QuantX is an open-source, event-driven trading engine and infrastructure focused on correctness, clarity, and long-term extensibility.

It is not built for one fixed type of user or one fixed workflow.

## Core Intent

QuantX provides a stable, domain-driven foundation for algorithmic trading systems.

The universal core is intentionally market-neutral. Market-specific behavior is isolated behind market modules and broker/data adapters. India is the first and only fully implemented market today; digital assets and other regions remain future work rather than current support.

## Design Stance

- **Infrastructure first** — QuantX is an engine and set of contracts, not a finished product for a single audience.
- **Composition over opinion** — Different use cases should be expressed through plugins, adapters, or separate projects, not by forcing everything into the core.
- **Same semantics where implemented** — Research, backtest, and paper share explicit domain and market-context contracts. LIVE remains a separate, constrained India-only boundary.
- **Correctness over features** — Execution integrity, recovery, and clear failure modes take priority over rapid feature expansion.
- **India as the first implementation** — The initial market module prioritizes NSE/BSE/F&O realities while keeping the universal core independent of Indian market rules.

## What Belongs in the Core

- Domain model (orders, fills, positions, portfolio, risk, execution lifecycle)
- Event-driven runtime and messaging
- Ports and adapter boundaries
- Deterministic research and simulation contracts
- Persistence and recovery foundations
- Capability and compatibility checks
- Market context and portable market-module contracts

## What Belongs Outside the Core

Different focuses should be built as plugins, adapters, or separate projects, for example:

- Broker-specific integrations
- Strategy frameworks or sample strategies
- Research notebooks and backtesting workflows
- User interfaces and dashboards
- AI / agent layers
- Specialized tools (options analytics, portfolio construction, monitoring, etc.)
- Opinionated products aimed at particular user groups

This keeps the core stable while allowing many different directions to grow around it.

## Long-Term Direction

QuantX aims to remain a reliable foundation that others (including future projects by the same author) can build on.

The project should stay useful to:

- People who want a clean execution and research engine
- People who want to build their own tools on top
- People who later create specialized plugins or products for different audiences

No single user type is treated as the only valid way to use QuantX.

## Guiding Rule

When adding something new, ask:

> Does this strengthen the core contracts and safety of the engine,  
> or does it belong as a plugin / adapter / separate project?

Prefer the second option whenever the feature is opinionated, audience-specific, or likely to change frequently.
