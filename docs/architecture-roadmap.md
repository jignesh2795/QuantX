# QuantX Architecture Roadmap

## Purpose

This document is the working index for the architecture and roadmap work. Detailed decisions live in `docs/architecture/` and will be recorded as ADRs.

## Architectural direction

QuantX is designed as a modular monolith first and distributed-ready later. The stable core is event-driven and domain-driven. External systems connect through ports and adapters. Optional capabilities are plugins. Broker and data integrations are adapters. Backtest, sandbox, paper and live share the same trading semantics.

## Core principles

1. Keep the core small and stable.
2. Use domain contracts for orders, fills, positions, portfolios, risk and execution.
3. Treat brokers and data providers as adapters.
4. Treat optional strategies, research, analytics and AI as plugins where practical.
5. Use capability negotiation rather than broker-name conditionals.
6. Keep UI and AI above the API/domain boundary.
7. Design F&O into the domain model from the beginning.
8. Maintain deterministic simulation and replayable trading events.
9. Prefer local-first operation while keeping deployment seams distributed-ready.
10. Integrate mature external libraries instead of rebuilding them.

## Master milestones

### M0 — Architecture
Domain contracts, event model, ports/adapters, plugin contracts, dependency rules and ADRs.

### M1 — Indian trading foundation
Instrument/contract model, NSE/BSE sessions, futures/options, margin and charges.

### M2 — Broker/data platform
Broker adapters, market-data adapters, capability negotiation and historical data.

### M3 — Simulation and research
Sandbox, paper execution, canonical event-driven backtesting, optimization and robustness.

### M4 — Strategy platform
Python strategy SDK, Strategy IR, visual Flow, scheduling, webhooks and external signal integrations.

### M5 — Control plane
REST, WebSocket, strategy registry, Action Center, monitoring, audit and operations.

### M6 — Intelligence and ecosystem
Options analytics, AI/agents, multi-account, security hardening, plugin registry, deployment options and later international/crypto adapters.

## Decision process

Research → Compare → Decide → Document → Build

No major QuantX implementation should begin until its architecture decision is documented and checked against existing projects.
