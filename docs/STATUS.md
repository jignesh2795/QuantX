# QuantX Status

## Current state
**Phase:** v0.1 implementation / execution-integrity, recovery, and LIVE-control hardening.

The repository contains an implemented domain, execution, research, India-market, integration, and reconciliation foundation. The active implementation track is execution-integrity hardening, developer-validation integrity, and stack integration.

**Latest externally validated recovery milestone:** `feat/production-recovery-entrypoint` at `efa4798a76d3576f31b5a2127381fb990c6a0915` with 665 passed, 0 failed, 0 errors, 0 skipped. The earlier 635-test checkpoint remains the last independently documented baseline on the pre-entrypoint recovery branch.

## Post-PR #33 validation evidence

The LIVE startup/readiness and trading-gate hardening merged in PR #33. Claude's local sandbox validation of the PR branch reached **813 passed tests, 0 failed** after aligning the affected fixtures with the new runtime/evidence contracts. Equivalent test fixes are included in the merged mainline, with an additional explicit unscoped negative-case correction. This is local validation evidence, not GitHub Actions evidence; Actions is not used as a repository gate while billing is disabled.

## Validation baseline

The current externally reported validation evidence for the production-recovery stack is **665 passed, 0 failed, 0 errors, 0 skipped** at `efa4798a76d3576f31b5a2127381fb990c6a0915`. This validation was run externally with OpenCode on `feat/production-recovery-entrypoint`; changed-file Ruff and `git diff --check` were clean. Repo-wide Ruff still reports 272 pre-existing errors. No production-broker end-to-end execution was claimed.

This checkpoint validates the LIVE durability hardening, pending-recovery corruption isolation, and explicit startup lifecycle: LIVE requires a UnitOfWork-backed transaction path; completed broker submissions retain a durable receipt even when idempotency completion is uncertain; direct LIVE dispatcher/adapter bypasses are blocked; durable trading-gate state survives restart; pending LIVE reservation context is persisted and reconstructible across a simulated process restart; malformed pending contexts are isolated as per-context recovery failures; the default all-required recovery path can resolve with local position/account evidence; concurrent recovery passes resolve a pending reservation at most once; and an explicit application runtime runs pending recovery once before startup completes. The 635-test suite completed with zero failures, errors, or skipped tests.

The 635-test validation was performed against the branch head after fast-forward sync at `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c`. The only Ruff finding was the pre-existing `I001` import-order issue in `src/quantx/application/execution.py`; a subsequent import-only cleanup was committed at `5817ce0f9cb2103f9ba05abfefa7495c5f2ec342`. `git diff --check` was clean; the local `uv.lock` modification was pre-existing environment noise and remained untouched. The import-only cleanup has not been independently re-run through the full suite in this environment.

This is the reported validation result for the checked commit. The available GitHub Actions status endpoint does not show an independent workflow run for this checkpoint, so this document does not claim GitHub CI independently executed that suite.

Recent continuation/recovery work includes:
- explicit continuation lifecycle reconstruction from authoritative receipt evidence;
- continuation-chain lineage and aggregate fill validation;
- idempotent continuation dispatch claims;
- pending/recoverable/resolved continuation recovery states;
- validation that reused continuation claims match authoritative receipt identity, quantity, account, and broker connection;
- conservative recovery of execution state rather than inference from an uncertain submission;
- durable trading-gate state persisted behind a pluggable state-store boundary, with SQLite restart coverage;
- versioned pending LIVE execution context persisted with idempotency reservations and reconstructible after restart;
- SQLite schema v2 migration coverage for pending context and durable trading-gate state;
- deterministic pending LIVE recovery with per-context failure isolation and no-submit semantics;
- malformed persisted-context isolation with reservation/context identity checks;
- explicit, one-shot application startup lifecycle for recovery-backed startup;
- broker-returned `UNKNOWN` LIVE receipts remain durably PENDING for reconciliation rather than completing idempotency.

## Architecture direction

- modular monolith first; distributed-ready later
- event-driven/domain-driven core
- ports and adapters
- capability-based integrations
- plugin-first extensibility
- Indian-market/F&O-first domain model
- data, control, and execution plane separation
- deterministic research, replay, and simulation
- explicit provenance and point-in-time market rules
- fail-closed live execution
- reconciliation rather than inference for uncertain broker outcomes
- local-first deployment with clear integration seams

## Current implementation track

Execution integrity and reconciliation remain the active track. The repository now covers idempotency, execution receipts, order lifecycle reconstruction, account/connection identity, broker-order reconciliation, bounded evidence refresh, uncertain-submission recovery, partial-fill continuation/recovery, durable trading-gate state, durable pending LIVE execution context, malformed-context isolation, explicit recovery-backed application startup, fail-closed handling of broker-returned UNKNOWN LIVE receipts, and concrete production startup composition with identity-bound Dhan recovery evidence. The Dhan production host adapter (`DhanHostConfig`/`DhanHostRuntime`) composes credentials/transport construction, exact account/connection registration, and one-shot recovery-backed startup with no broker-submit surface and no new execution semantics. A vendor-neutral local market-data store (`MarketDataStore`, SQLite-backed) persists canonical quotes/candles with exact Decimal fidelity, deterministic chronological retrieval, idempotent-duplicate/conflicting-duplicate semantics, and schema v3 migration; Dhan remains an adapter above that storage boundary. A vendor-neutral dataset catalog registers immutable `DatasetVersion` identities with idempotent-duplicate/conflicting-duplicate semantics and local JSON metadata persistence, without verifying source content or performing ingestion. A deterministic historical-data quality seam analyzes canonical candle collections for structural soundness and assesses completeness only against an explicitly supplied expected timestamp set, reporting UNKNOWN completeness otherwise, without repairing data or verifying source files. A dataset-backed historical research access seam resolves a registered `(dataset_id, version)` through the catalog and reads version/source-scoped canonical candles from `MarketDataStore` without source verification, backtesting, simulation, or scheduled operation. A canonical historical candle ingestion bridge (`research/market_data_ingestion.py`) connects `MarketDataPort` to `MarketDataStore` with no scheduling, retry, caching, or network behavior; there is no claim of scheduled ingestion, production historical-data operation, or real-broker end-to-end execution. Historical research observations (`HistoricalObservation`) now preserve canonical candles losslessly alongside quote snapshots: `HistoricalObservation.from_candle` keeps the exact `Candle` (instrument, timeframe, timestamp, OHLCV) with no Quote projection and no synthetic bid/ask, `HistoricalDataSeries`/`HistoricalReplay` stay payload-neutral over both payload types, and dataset-backed candles convert through `research/dataset_access.py` without touching `MarketDataStore`, catalog, or identity rules. This does not implement backtesting or execution simulation, does not verify source integrity, and does not add scheduled/production historical ingestion.

`PendingExecutionRecoveryRunner` remains a deterministic application service with no broker-submit capability. The current hardening branch also makes LIVE execution depend on a started recovery-backed `ApplicationRuntime` and adds submission-time trading-gate authorization spanning durable reservation and the broker call. `ApplicationRuntime` now provides the explicit one-shot startup lifecycle seam: it requires a recovery hook, runs it synchronously before marking the runtime started, rejects repeated starts, and leaves startup failed if recovery infrastructure raises. `ProductionRuntime` now provides the concrete process-composition boundary: it owns the durable SQLite lifecycle, accepts explicit registry configuration, delegates to the recovery-backed `ApplicationRuntime`, and closes persistence on composition failure. It intentionally does not construct credentials, broker transports, or deployment-specific services. Therefore this is validated production composition, not a claim of an executable CLI/service deployment or real-broker end-to-end startup.

The continuation implementation deliberately remains persistence-agnostic: it consumes authoritative receipt/reconciliation contracts and does not introduce a database or broker network dependency by itself.

## Current adversarial findings

The latest review of the 20-commit recovery sequence identified two additional LIVE control-path gaps: startup recovery was not a required dependency of `ExecutionOrchestrator`, and the gate check could race with broker submission. The current hardening branch addresses both. These changes are documented as implementation work pending independent validation; they do not rewrite the earlier historical validation checkpoints.

## Documentation policy

Architecture documents distinguish implemented/current behavior, target architecture, and roadmap/future capabilities. Historical batch records should not be treated as current implementation state unless explicitly marked as historical.

## Next direction

Before adding UI, AI, or a broad broker matrix, keep the current package boundaries stable. The LIVE/recovery boundary and production composition are implemented and externally validated. Issue #22 is now implemented as the Dhan production host slice on this branch: the production host/deployment boundary is documented in `docs/architecture/50-production-host-integration-boundary.md`; `ProductionRuntime` is implemented; Dhan host composition (`DhanHostConfig`/`DhanHostRuntime`/`build_dhan_host_runtime`) is the current implementation slice with 678/678 local tests passing. GitHub Actions is not treated as validation evidence in this repository; OpenCode/local validation is the current execution gate. No production-broker end-to-end execution has been performed.

`uv.lock` may remain locally modified by environment operations and is not a project change unless dependencies intentionally change. GitHub Actions runs observed for this branch fail before executing workflow steps, so they are not treated as code-validation evidence.
