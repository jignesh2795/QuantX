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

### R1-C deterministic research and provenance sequence

The completed R1-C sequence is:

`C1 historical fidelity ✅ → C2 data-quality contract ✅ → C3 calendar/gap semantics ✅ → C4 historical account state ✅ → C5 transaction-cost model ✅ → C6 execution-price/fill fidelity ✅ → C7 time-indexed account-state sampling ✅ → C8 valuation provenance ✅ → C9 multi-instrument synchronization ✅ → C10 backtest provenance binding ✅ → C11 dataset identity/evidence ✅ → C12 canonical research-run configuration ✅ → C13 research persistence/orchestration/experiments ✅`

### R1-C13 — Research persistence and experiments

C13 is complete through C13.8. It established durable SQLite research persistence, research-run orchestration and lifecycle binding, run rehydration, experiment comparison and association, metadata ownership and persistence, experiment detail reads, and the thin experiment write boundary.

C13 preserves the existing provenance and persistence seams; it does not introduce a competing research identity system.

### R1-C14 — Deterministic Historical Dataset Ingestion & Provenance Composition

C14 is in progress: the ingestion boundary (C14.2), provider composition (C14.3), identity binding (C14.4), quality binding (C14.5), and durable persistence composition (C14.6) are implemented, the Dhan vertical proofs (C14.7) are covered by dedicated composition tests, and ingestion results bind to the canonical research-run identity (C14.8). It composes the existing `MarketDataPort`, dataset identity/catalog, historical-data quality, `MarketDataStore`, dataset-backed research access, and research provenance boundaries into one deterministic historical ingestion workflow.

The canonical lifecycle is:

`pre-registered DatasetVersion → provider/MarketDataPort → C14 ingestion boundary → canonical candles → quality evidence → MarketDataStore → dataset-backed read → ResearchProvenance/ResearchRun`

C14 is provider-neutral. Dhan is a concrete vertical proof, not the domain boundary. Existing Dhan/dataset branches are salvage sources and are not to be merged wholesale.

The next target is C14.9, the end-to-end deterministic proof; C14.8 provenance binding is complete.

C14 explicitly defers scheduling, streaming, distributed ingestion, cloud storage, generic ETL, production historical-data service, UI, AI/ML, optimization, and broad broker expansion.

The C14 planning record is maintained separately from this master roadmap; remaining work is the C14.9 end-to-end deterministic proof.

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
