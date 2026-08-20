# ADR-007: Modular-Hybrid Architecture

Status: Accepted for architecture planning

## Context

QuantX needs to serve several workloads with different characteristics: local development, deterministic backtesting, paper trading, live execution, research, broker integration, external APIs, and optional AI capabilities. A full microservice design would add operational complexity too early, while a tightly coupled monolith would make broker, strategy, data and UI changes expensive.

The reference projects suggest a hybrid approach. NautilusTrader combines an event-driven core with modular adapters and consistent research/live semantics. Hummingbot uses modular connectors plus controllers and executors. OpenAlgo separates broker integrations and exposes a broader control-plane/application surface. QuantumTrade already provides useful event, risk, execution and session foundations.

## Decision

QuantX will use a **modular monolith first, distributed-ready later** architecture.

The core process will contain stable domain and application modules with strict interfaces. Plugins and adapters will extend capabilities without modifying the core domain. Communication between modules will prefer explicit ports and domain events over direct framework-specific dependencies.

The architecture will expose three logical planes:

1. **Data plane** — market data, normalized events, historical/replay inputs.
2. **Control plane** — API, strategy registry, scheduling, authentication, monitoring and human actions.
3. **Execution plane** — broker adapters, order submission, fills, reconciliation and live safety.

The planes may run in a single process for local deployments. They may later be separated into worker processes or services without changing domain contracts.

## Rules

- Core domain code must not depend on broker, UI, AI-provider or storage implementations.
- Brokers and data sources are adapters.
- Optional capabilities are plugins when practical.
- Strategy logic emits intents; the core owns risk and order lifecycle.
- Backtest, replay, paper and live use the same order/fill/position semantics.
- Message transport is abstracted behind a port; in-memory transport is valid for local mode.
- Storage is abstracted behind ports; local DuckDB/Parquet or other lightweight stores can be used first.
- Plugins declare capabilities, version compatibility and permissions.
- Live execution requires explicit safety state and cannot be reached by bypassing core risk/policy checks.

## Why not microservices first?

The initial user and contributor experience should be easy to run locally. Microservices would make development, testing and installation harder before there is evidence of a scaling requirement. The architecture instead preserves seams where components can be moved out-of-process later.

## Consequences

### Positive

- Simple local installation.
- Strong separation of concerns.
- Easier plugin/community development.
- Multiple deployment topologies without redesigning the domain.
- Clear boundaries for security and testing.
- Better fit for a self-hosted open-source project.

### Negative

- Requires disciplined interfaces and dependency rules.
- Some modules will initially appear more abstract than necessary.
- Distributed deployment will require later operational work.

## Revisit conditions

Reconsider process separation when one or more of the following becomes true:

- research workloads materially interfere with live trading;
- multiple independent execution workers are required;
- event volume exceeds the safe capacity of a single runtime;
- broker/data adapters need independent failure domains;
- external users require separately scalable API and worker tiers.
