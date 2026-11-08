# QuantX Roadmap

## Current work programme — 2026-11-08

**Main baseline reviewed for M4 closeout:** `d2442bbbafab3eca91f27a8c3d8fdd65e3f61b80` (PR #325 documentation reconciliation merged; PR #324 remains the F4.5.4 implementation merge). The India market-module migration is complete, with `quantx.markets.india` canonical and the legacy `quantx.india` shim retained. India remains the only implemented market; digital assets remains an interface-only placeholder.

Use the [QuantX Master Work Programme](../planning/quantx-work-program-2026-10.md) as the current cross-workstream sequencing record. The pinned-source comparison is documented in [Global Trading Architecture Comparison — 2026-11-07](../research/2026-11-global-architecture-comparison.md) and merged in PR #315. The bounded M4.5 declarative Flow-to-existing-runtime vertical is complete: F4.5.1–F4.5.4 are merged in PRs [#317](https://github.com/jignesh2795/QuantX/pull/317), [#320](https://github.com/jignesh2795/QuantX/pull/320), [#321](https://github.com/jignesh2795/QuantX/pull/321) and [#324](https://github.com/jignesh2795/QuantX/pull/324). PR #324 merged at `4a1a5f7629fff832dcec74471dae096f2d231733` from validated candidate `3b0566988ed336034b93d0782ec3a693aca3f153`; issue #322 is closed. The single documented M4 exit criterion is now met; M4 is complete at the milestone level. The next actionable programme item is the read-only #202 dead-module/Dhan-transport audit. #267 remains blocked pending a credible alternative authoritative provider/source; #266 remains blocked by the missing 0/7 required fixtures. Public-readiness work (#190 and #199) remains open. Actions/paid CI is not part of the validation plan.

The milestone history below is not a substitute for checking current issue state and exact-SHA validation evidence. The master roadmap is grouped into milestones rather than treating every feature as an independent project.

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

`C1 historical fidelity ✅ → C2 data-quality contract ✅ → C3 calendar/gap semantics ✅ → C4 historical account state ✅ → C5 transaction-cost model ✅ → C6 execution-price/fill fidelity ✅ → C7 time-indexed account-state sampling ✅ → C8 valuation provenance ✅ → C9 multi-instrument synchronization ✅ → C10 backtest provenance binding ✅ → C11 dataset identity/evidence ✅ → C12 canonical research-run configuration ✅ → C13 research persistence/orchestration/experiments ✅ → C14 deterministic dataset ingestion/provenance composition ✅`

### R1-C13 — Research persistence and experiments

C13 is complete through C13.8. It established durable SQLite research persistence, research-run orchestration and lifecycle binding, run rehydration, experiment comparison and association, metadata ownership and persistence, experiment detail reads, and the thin experiment write boundary.

C13 preserves the existing provenance and persistence seams; it does not introduce a competing research identity system.

### R1-C14 — Deterministic Historical Dataset Ingestion & Provenance Composition

C14.1–C14.9 are complete: the ingestion boundary (C14.2), provider composition (C14.3), identity binding (C14.4), quality binding (C14.5), and durable persistence composition (C14.6) are implemented, the Dhan vertical proofs (C14.7) are covered by dedicated composition tests, ingestion results bind to the canonical research-run identity (C14.8), and the end-to-end deterministic proof (C14.9) passes. It composes the existing `MarketDataPort`, dataset identity/catalog, historical-data quality, `MarketDataStore`, dataset-backed research access, and research provenance boundaries into one deterministic historical ingestion workflow.

The canonical lifecycle is:

`pre-registered DatasetVersion → provider/MarketDataPort → C14 ingestion boundary → canonical candles → quality evidence → MarketDataStore → dataset-backed read → ResearchProvenance/ResearchRun`

C14 is provider-neutral. Dhan is a concrete vertical proof, not the domain boundary. Existing Dhan/dataset branches are salvage sources and are not to be merged wholesale.

C14.8 provenance binding and the C14.9 end-to-end deterministic proof are complete; all C14 slices are implemented.

C14 explicitly defers scheduling, streaming, distributed ingestion, cloud storage, generic ETL, production historical-data service, UI, AI/ML, optimization, and broad broker expansion.

The detailed C14 planning record remains implementation history. C14.9 is merged on `main` in PR #158. V0.1 local-first host/integration readiness is acceptance-complete for the declared programmatic-library scope under ADR-008; it is not the next milestone.

## V0.1 Local-First Host & Integration Readiness — acceptance-complete

**Status:** Complete for the declared programmatic local-first library scope under ADR-008; see `docs/architecture/28-v0.1-acceptance-criteria.md`. The sequence below is retained as historical implementation planning, not a statement of pending work. The CLI remains explicitly deferred.

### Objective

Close the gap between QuantX's tested application components and a documented, executable local process lifecycle. Start with an audit, not a greenfield host or broad subsystem.

### Sequence

1. **Acceptance audit:** locate the canonical v0.1 acceptance criteria, repair any stale documentation references, and map each criterion to current code, tests, and evidence.
2. **Host gap analysis:** inspect `ProductionRuntime`, `ApplicationRuntime`, the Dhan host composition, configuration, and existing command-line/package entrypoints. Identify the smallest missing operational seam; do not assume a new CLI or server is needed until the inventory is complete.
3. **Minimal local entrypoint:** if the audit proves a gap, compose existing components using explicit configuration. Keep credentials and vendor transports outside domain/application core, choose no default account or connection, and make startup recovery complete before the host reports execution readiness.
4. **Lifecycle and recovery proof:** test startup success/failure, pending-recovery visibility, fail-closed behavior, database/resource closure, and restart behavior with SQLite and in-memory adapters. The host must not submit a broker order during startup recovery.
5. **Release evidence:** document the supported local invocation, prerequisites, configuration fields, shutdown behavior, and exact local validation commands. Mark v0.1 release readiness only against explicit acceptance criteria.

### Exit criteria

- Every v0.1 criterion has a code/test/evidence mapping or an explicit blocker.
- One supported local invocation exercises the documented host lifecycle, or the audit demonstrates why a host entrypoint is out of scope for v0.1.
- Recovery failure prevents readiness; no default account, connection, credentials, or broker is silently selected.
- Shutdown closes process-owned resources and restart tests verify durable state as applicable.
- Focused and full local tests, Ruff, mypy where configured, and `git diff --check` pass at the exact reviewed commit.
- No UI, AI/agent subsystem, cloud/distributed worker architecture, broad broker matrix, or real-broker order testing is introduced as part of this milestone. A local integration pass does not constitute production LIVE certification.

### Guardrail

Execution/recovery internals are frozen unless the acceptance audit finds a concrete invariant violation. Preserve the existing ports, adapters, persistence, reconciliation, and provenance boundaries; do not add parallel abstractions.

## M4 — Strategy Platform

**Status:** **Complete** against the canonical M4 exit criterion. The milestone is complete at the defined scope; this does not claim that all later strategy-platform surfaces are delivered.

M4.1 proves the existing Python strategy definition/IR/runtime path through deployment-owned context binding, risk/policy preparation, and the canonical paper executor. It is offline and PAPER-only. It establishes the Python half of the M4 exit criterion; the Flow half and cross-language runtime parity were completed later in M4.5.

**Parent M4 runtime-parity criterion — MET:** Python strategies and a first Flow path compile to the same runtime semantics through M4.5.3 and use the same offline downstream consumers through M4.5.4. The adapter implements the existing `ExecutableStrategy` contract and runs through `StrategyRuntime`; the semantic parity test compares Python and Flow `StrategyResult` behavior. PR #324 proves deployment-owned binding, preparation, risk/policy and offline PAPER/BACKTEST integration. Issue #197 is complete in PR #221. The normative QX-08 v3.2.0 brief settles G1 timer causality/cohort ordering, G2 commit-preserving callback failures, G3 shared evidence projection, and standalone T8 no-LIVE boundary coverage. QX-08 implementation under issue #196 has completed M1 in PR #224, M2 in PR #226 (validated feature HEAD `75f8b0e2858d1ba11d1e7cd3c32f2fc6a6c2df1e`, merge commit `e150350ce747f88845227a70c35a9f94c8e7cd83`), M3 in PR #229 (validated feature HEAD `ebc67365ce589e50b0477de1b790885b4916c3e7`; merge commit `6f84259b8e6281576eead0831082067283baddeb`), and M4 in PR #232 (validated feature HEAD `40559841bc94e3b4c1c7482b21528300c895d7e4`; merge commit `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4`). The normative QX-08 v3.2.0 T1–T8/G1–G3 acceptance reconciliation is complete in PR #234 and issue #196 is closed. Do not reopen QX-08 or describe M2/M3/M4 as pending. The first callback-enabled vertical rejects nonzero execution-latency profiles unless a future event-time execution integration is separately approved; no scheduler or execution/recovery redesign is included.

The Python strategy path and Strategy IR are implemented. The visual Flow editor/workflow persistence, external scheduling, webhooks/external signals, streaming, AI nodes and cloud-worker surfaces remain later platform capabilities; they are not M4 exit criteria. Public API publication remains separately tracked in #199.

### M4.5 — Declarative Flow-to-existing-runtime parity (F4.5.1–F4.5.4 complete)

The completed bounded product vertical delivered the smallest declarative Flow compiler/runtime adapter

The bounded implementation sequence is:

1. **F4.5.1 — complete in [PR #317](https://github.com/jignesh2795/QuantX/pull/317):** immutable typed/versioned Flow graph contract, canonical identity, closed v1 node/port catalogue and pure graph validator. Validated candidate `97d1647194405dbd778c51d38b6b92ee3190e154`; merge `521fb6ed76dffc30d23d89333923dd6b81c6b293`; issue #316 closed.
2. **F4.5.2 — complete in [PR #320](https://github.com/jignesh2795/QuantX/pull/320):** pure deterministic compiler/interpreter for the validated minimal node set. Validated candidate `cea48214db4089efa0361fb5e3bc05e5818aeb5f`; merge `c659d4eb3d5aee74b78003cc9dfd112287bb78d6`; issue #319 closed.
3. **F4.5.3 — complete in [PR #321](https://github.com/jignesh2795/QuantX/pull/321):** adapter implementing the existing `ExecutableStrategy` protocol, invoked through `StrategyRuntime`, with Python/Flow semantic parity tests. Validated candidate `966fce2d32d4b9609aeb0d88ed2250e6af301881`, based on `c659d4eb3d5aee74b78003cc9dfd112287bb78d6`; merged at `a27b93f56f978b56a9d3a3373d8221d40ad6fd81`.
4. **F4.5.4 — complete in [PR #324](https://github.com/jignesh2795/QuantX/pull/324):** offline PAPER rehearsal and deterministic BACKTEST integration through the existing deployment binding, `StrategyExecutionPreparer`, risk/policy and canonical simulated execution. Validated candidate `3b0566988ed336034b93d0782ec3a693aca3f153`; merge `4a1a5f7629fff832dcec74471dae096f2d231733`; issue #322 closed.

Flow graph structure remains separate from `StrategyIR.parameters`; optional/missing inputs stay explicit, and history remains bounded, same-instrument and strictly prior. The adapter does not add another runtime or strategy-result model. F4.5.4 has now demonstrated that Flow uses the existing offline downstream paths without bypassing deployment, risk, policy or preparation boundaries. The M4.5 sequence completes the canonical M4 runtime-parity exit criterion. The next actionable programme item is the read-only #202 dead-module/Dhan-transport audit.

Do not introduce direct order/broker/REST nodes, arbitrary Python, scheduler, webhooks, streaming, AI nodes, cloud workers, cross-market support, UI or LIVE capabilities. A visual editor and workflow persistence are later slices after the language/runtime contract is stable.

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

### R1-C9 — Multi-instrument account-state synchronization (complete)

C9 is implemented and merged. It adds a separate time-indexed account-state series to backtests without changing the existing execution-event snapshots. Sampling occurs at replay-frame timestamps before current-frame strategy/execution effects, uses explicit current-frame marks for complete valuation, and becomes incomplete rather than reusing a stale mark. The policy distinguishes exact-current evidence from explicitly selected as-of-observed evidence without hiding mark age or admitting future data. See the historical C9 milestone record in `docs/STATUS.md`.

C9 is research/backtest-only. It does not change LIVE execution, risk, broker, reconciliation, retry, UNKNOWN, recovery, or capital semantics.
