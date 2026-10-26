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

**Status:** Active at the parent Strategy Platform level; QX-08's bounded M1–M4 implementation sequence is complete. M4.1 deterministic strategy-to-paper rehearsal merged in PR #218. QX-09, the market-pack pre-trade-check pipeline tracked by issue #197, is complete in PR #221 (validated feature head `7793646e0e3d210e81364d39605ee3383e434723`; merge commit `1e4ebf4f4671e90dcdcafc1cda578182ab39d58b`). QX-08 M1 is complete in PR #224 (validated feature head `0e9dd86401dae244b0c2546af528211a7039346d`; merge commit `8f1cc49c143fd5ee866be81fe366763700db1ac5`), M2 is complete in PR #226 (validated feature head `75f8b0e2858d1ba11d1e7cd3c32f2fc6a6c2df1e`; merge commit `e150350ce747f88845227a70c35a9f94c8e7cd83`), M3 is complete in PR #229 (validated feature head `ebc67365ce589e50b0477de1b790885b4916c3e7`; merge commit `6f84259b8e6281576eead0831082067283baddeb`), and M4 paper/backtest driver parity is complete in PR #232 (validated feature HEAD `40559841bc94e3b4c1c7482b21528300c895d7e4`; merge commit `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4`). Validation results are recorded in the respective PRs as operator-reported local evidence; no GitHub Actions results are claimed and repository Actions remain disabled by project policy.

M4.1 proves the existing Python strategy definition/IR/runtime path through deployment-owned context binding, risk/policy preparation, and the canonical paper executor. It is offline and PAPER-only; it does not complete M4 overall, add a Flow authoring path, or establish Python/Flow runtime parity.

**Parent M4 exit criterion remains:** Python strategies and a first Flow path compile to the same runtime semantics. That Flow authoring/runtime-parity slice remains separate parent Strategy Platform roadmap work and is not part of QX-08 scope. Issue #197 is complete in PR #221. The normative QX-08 v3.2.0 brief settles G1 timer causality/cohort ordering, G2 commit-preserving callback failures, G3 shared evidence projection, and standalone T8 no-LIVE boundary coverage. QX-08 implementation under issue #196 has completed M1 in PR #224, M2 in PR #226 (validated feature HEAD `75f8b0e2858d1ba11d1e7cd3c32f2fc6a6c2df1e`, merge commit `e150350ce747f88845227a70c35a9f94c8e7cd83`), M3 in PR #229 (validated feature HEAD `ebc67365ce589e50b0477de1b790885b4916c3e7`; merge commit `6f84259b8e6281576eead0831082067283baddeb`), and M4 in PR #232 (validated feature HEAD `40559841bc94e3b4c1c7482b21528300c895d7e4`; merge commit `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4`). The next QX-08 step is acceptance-matrix reconciliation of its in-scope v3.2.0 criteria before closing issue #196. The first callback-enabled vertical rejects nonzero execution-latency profiles unless a future event-time execution integration is separately approved; no scheduler or execution/recovery redesign is included.

Python SDK, Strategy IR, visual Flow, scheduling, webhooks and external signals remain the broader M4/platform roadmap.

## M5 — Control Plane
REST, WebSocket, strategy registry, Action Center, monitoring, audit and operations.

## M6 — Intelligence and Ecosystem
Options analytics, AI/agents, multi-account, security hardening, plugin registry, deployment and later international/crypto adapters.

### Digital-assets market expansion — proposed future work, not active implementation

QuantX retains a path to crypto through its market-neutral core, but no crypto venue adapter or digital-assets market pack is currently implemented. The India-first and execution-safety priorities remain authoritative; this work must not interrupt the active correctness and Strategy Platform sequence. The proposal begins with a code-backed compatibility audit, then one-venue spot data, deterministic research/backtest, paper trading, venue test-environment validation where available, and only then a separately gated LIVE spot path. Derivatives and cross-venue portfolios are later scopes.

See [Digital-Assets Market Expansion](digital-assets-market-expansion.md) for phase gates and acceptance criteria and [the planning proposal](../planning/crypto-market-extension-plan.md) for detailed design context. No change to LIVE region authorization is implied.

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
