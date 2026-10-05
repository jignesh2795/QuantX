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

`C1 canonical historical fidelity ✅ → C2 data-quality contract ✅ → C3 calendar-aware gap semantics ✅ → C4 historical account state ✅ → C5 transaction-cost model ✅ → C6 execution price/fill fidelity ✅ → C7 time-indexed account-state sampling ✅`

R1-C1 through R1-C7 are merged and externally revalidated. The next slice is selected from the remaining deterministic-research/account-state gaps rather than opening UI, AI, or broad broker-matrix work.

The R1-C6 planning and implementation record is in `r1-c6-execution-fidelity.md`.
The R1-C7 planning and implementation record is in `r1-c7-time-indexed-account-state.md`.
The selected next slice is documented in `r1-c8-account-state-valuation-provenance.md`.

## M4 — Strategy Platform
Python SDK, Strategy IR, visual Flow, scheduling, webhooks and external signals.

## M5 — Control Plane
REST, WebSocket, strategy registry, Action Center, monitoring, audit and operations.

## M6 — Intelligence and Ecosystem
Options analytics, AI/agents, multi-account, security hardening, plugin registry, deployment and later international/crypto adapters.

## Release philosophy

Start with a useful, local-first engine and grow platform breadth without moving responsibilities into the core unnecessarily.


### R1-C7 — Time-indexed account-state sampling

C7 adds a separate time-indexed account-state series to backtests without changing the existing execution-event snapshots.

The series is sampled at replay-frame timestamps before the current frame's strategy/execution effects, uses only explicit current-frame marks for complete valuation, and becomes incomplete rather than reusing a stale mark. Existing C4 receipt-driven account-state snapshots remain unchanged.


### R1-C8 — Account-state valuation provenance

The next deterministic-research slice strengthens the evidence carried by historical account-state snapshots.

C8 will make the explicit market marks used by a snapshot auditable at the snapshot boundary, including their instrument identity, source, observation timestamp, and whether valuation evidence was unavailable. It will reuse the existing mark and tracker boundaries rather than adding a second valuation/accounting path.

C8 is research/backtest only. It does not change LIVE execution, risk, broker, reconciliation, retry, UNKNOWN, recovery, or capital semantics.
