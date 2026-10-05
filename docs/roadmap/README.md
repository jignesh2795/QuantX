# QuantX Roadmap

The master roadmap is grouped into milestones rather than treating every feature as an independent project.

## M0 — Architecture
Core contracts, event model, ports/adapters, plugin model, capability negotiation, dependency rules and ADRs.

## M1 — Indian Trading Foundation
Equities, ETFs, indexes, futures, options, sessions, contracts, margin and charges.

## M2 — Broker and Data Platform
Broker/data adapters, capability discovery, historical data, Historify-style local data management.

## M3 — Simulation and Research
Sandbox, paper execution, canonical backtesting, optimization, walk-forward, robustness and scenario testing.

### R1-C execution-fidelity sequence

The current execution/research hardening sequence is:

`C1 canonical historical fidelity ✅ → C2 data-quality contract ✅ → C3 calendar-aware gap semantics ✅ → C4 historical account state ✅ → C5 transaction-cost model ✅ → C6 execution price/fill fidelity ✅`

R1-C6 is merged and externally revalidated. The next slice is selected from the remaining deterministic-research/account-state gaps rather than opening UI, AI, or broad broker-matrix work.

The R1-C6 planning and implementation record is in `r1-c6-execution-fidelity.md`.

## M4 — Strategy Platform
Python SDK, Strategy IR, visual Flow, scheduling, webhooks and external signals.

## M5 — Control Plane
REST, WebSocket, strategy registry, Action Center, monitoring, audit and operations.

## M6 — Intelligence and Ecosystem
Options analytics, AI/agents, multi-account, security hardening, plugin registry, deployment and later international/crypto adapters.

## Release philosophy

Start with a useful, local-first engine and grow platform breadth without moving responsibilities into the core unnecessarily.
