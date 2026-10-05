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

`C1 canonical historical fidelity ✅ → C2 data-quality contract ✅ → C3 calendar-aware gap semantics ✅ → C4 historical account state ✅ → C5 transaction-cost model ✅ → C6 execution price/fill fidelity ✅ → C7 time-indexed account-state sampling ✅ → C8 account-state valuation provenance ✅`

R1-C1 through R1-C8 are merged and externally revalidated. The next slice is selected from the remaining deterministic-research/account-state gaps rather than opening UI, AI, or broad broker-matrix work.

The R1-C6 planning and implementation record is in `r1-c6-execution-fidelity.md`.
The R1-C7 planning and implementation record is in `r1-c7-time-indexed-account-state.md`.
The R1-C8 planning and implementation record is in `r1-c8-account-state-valuation-provenance.md`.
The selected next slice is documented in `r1-c9-multi-instrument-account-state-synchronization.md`.

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

R1-C8 made the evidence carried by historical account-state snapshots explicitly auditable.

R1-C8 is complete: immutable valuation evidence records identify the instrument, mark, source, observation time, snapshot selection time, availability, and explicit unavailability reason. C8 reused the existing mark/tracker boundary and did not alter valuation selection rules.

C8 is research/backtest only. It does not change LIVE execution, risk, broker, reconciliation, retry, UNKNOWN, recovery, or capital semantics.

### R1-C9 — Multi-instrument account-state synchronization

The next deterministic-research slice will define and implement an explicit synchronization policy for time-indexed account-state sampling when a replay frame updates only one of several open-position instruments. The policy must distinguish exact-current evidence from deterministic as-of evidence and must never hide mark age or silently use future data.

C9 is research/backtest only. It does not change LIVE execution, risk, broker, reconciliation, retry, UNKNOWN, recovery, or capital semantics.
