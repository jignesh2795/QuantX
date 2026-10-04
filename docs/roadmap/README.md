# QuantX Roadmap

The roadmap has two levels:

1. **Tight phases** (`PHASES.md`) — near-term build units with one outcome each
2. **Milestones M0–M6** — longer-range product map

Use tight phases for day-to-day sequencing. Use milestones for direction.

## Tight phases (near-term)

See **[PHASES.md](./PHASES.md)** for the ordered list:

P0 Domain spine → P1 Receipts & idempotency → P2 Trading gate & reservation → P3 Recovery-backed startup → P4 UNKNOWN handling → P5 Continuation & partial fills → P6 Host composition slice → P7 Pre-trade risk contracts → P8 Position/portfolio on evidence → P9 Fill honesty → P10 Research replay → P11 Next broker adapter → P12+ Plugins/surfaces

**Rule:** one primary outcome per phase; split if validation cannot be focused.

## Milestones (long-range)

### M0 — Architecture
Core contracts, event model, ports/adapters, plugin model, capability negotiation, dependency rules and ADRs.

### M1 — Indian Trading Foundation
Equities, ETFs, indexes, futures, options, sessions, contracts, margin and charges.

### M2 — Broker and Data Platform
Broker/data adapters, capability discovery, historical data, local data management.

### M3 — Simulation and Research
Sandbox, paper execution, canonical backtesting, optimization, walk-forward, robustness and scenario testing.

### M4 — Strategy Platform
Python SDK, Strategy IR, visual Flow, scheduling, webhooks and external signals.

### M5 — Control Plane
REST, WebSocket, strategy registry, Action Center, monitoring, audit and operations.

### M6 — Intelligence and Ecosystem
Options analytics, AI/agents, multi-account, security hardening, plugin registry, deployment and later international/crypto adapters.

## Release philosophy

Start with a useful, local-first engine and grow platform breadth without moving responsibilities into the core unnecessarily.

Execution integrity tight phases (P1–P6) should be signed off before broad expansion into product surfaces (M4–M6).
