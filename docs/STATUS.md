# QuantX Status

## Current state
**Authoritative main:** `bb3e710eaaefbe70f8a4c5026ad07a3ab0f1aa84`

**R1-C1 through R1-C12:** complete.

**R1-C13:** complete through C13.8, including durable research persistence, research-run orchestration and lifecycle binding, rehydration, experiment comparison/association/metadata persistence, experiment detail read, and the experiment write boundary.

**Current planning target:** **R1-C14 — Deterministic Historical Dataset Ingestion & Provenance Composition.** C14 is planning-only at this state; implementation must compose the existing vendor-neutral market-data, dataset identity, quality, persistence, dataset-access, and research-provenance seams rather than introduce duplicate subsystems.

The repository contains an implemented domain, execution, research, India-market, integration, reconciliation, and deterministic research foundation. Historical validation records below are retained as evidence/history and do not define the current milestone.

**Latest externally validated recovery milestone:** `feat/production-recovery-entrypoint` at `efa4798a76d3576f31b5a2127381fb990c6a0915` with 665 passed, 0 failed, 0 errors, 0 skipped. The earlier 635-test checkpoint remains the last independently documented baseline on the pre-entrypoint recovery branch.

## Post-PR #33 validation evidence

The LIVE startup/readiness and trading-gate hardening merged in PR #33. Claude's local sandbox validation of the PR branch reached **813 passed tests, 0 failed** after aligning the affected fixtures with the new runtime/evidence contracts. Equivalent test fixes are included in the merged mainline, with an additional explicit unscoped negative-case correction. This is local validation evidence, not GitHub Actions evidence; Actions is not used as a repository gate while billing is disabled.

## Validation baseline

The current externally reported validation evidence for the production-recovery stack remains **665 passed, 0 failed, 0 errors, 0 skipped** at `efa4798a76d3576f31b5a2127381fb990c6a0915`. This validation was run externally with OpenCode on `feat/production-recovery-entrypoint`; changed-file Ruff and `git diff --check` were clean. Repo-wide Ruff still reports 272 pre-existing errors. No production-broker end-to-end execution was claimed.

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

Execution integrity and reconciliation remain the active track. The repository now covers idempotency, execution receipts, order lifecycle reconstruction, account/connection identity, broker-order reconciliation, bounded evidence refresh, uncertain-submission recovery, partial-fill continuation/recovery, durable trading-gate state, durable pending LIVE execution context, malformed-context isolation, explicit recovery-backed application startup, fail-closed handling of broker-returned UNKNOWN LIVE receipts, and concrete production startup composition with identity-bound Dhan recovery evidence. The Dhan production host adapter (`DhanHostConfig`/`DhanHostRuntime`) composes credentials/transport construction, exact account/connection registration, and one-shot recovery-backed startup with no broker-submit surface and no new execution semantics. A vendor-neutral local market-data store (`MarketDataStore`, SQLite-backed) persists canonical quotes/candles with exact Decimal fidelity, deterministic chronological retrieval, idempotent-duplicate/conflicting-duplicate semantics, and schema v3 migration; Dhan remains an adapter above that storage boundary. A vendor-neutral dataset catalog registers immutable `DatasetVersion` identities with idempotent-duplicate/conflicting-duplicate semantics and local JSON metadata persistence, without verifying source content or performing ingestion. A deterministic historical-data quality seam analyzes canonical candle collections for structural soundness and assesses completeness only against an explicitly supplied expected timestamp set, reporting UNKNOWN completeness otherwise, without repairing data or verifying source files. A dataset-backed historical research access seam resolves a registered `(dataset_id, version)` through the catalog and reads version/source-scoped canonical candles from `MarketDataStore` without source verification, backtesting, simulation, or scheduled operation. A canonical historical candle ingestion bridge (`research/market_data_ingestion.py`) connects `MarketDataPort` to `MarketDataStore` with no scheduling, retry, caching, or network behavior; there is no claim of scheduled ingestion, production historical-data operation, or real-broker end-to-end execution. Historical research observations (`HistoricalObservation`) now preserve canonical candles losslessly alongside quote snapshots: `HistoricalObservation.from_candle` keeps the exact `Candle` (instrument, timeframe, timestamp, OHLCV) with no Quote projection and no synthetic bid/ask, `HistoricalDataSeries`/`HistoricalReplay` stay payload-neutral over both payload types, and dataset-backed candles convert through `research/dataset_access.py` without touching `MarketDataStore`, catalog, or identity rules. This does not implement backtesting or execution simulation, does not verify source integrity, and does not add scheduled/production historical ingestion. The deterministic backtest path now accepts candle-backed replay frames through the existing event and reference-price contracts (candle events carry the exact `Candle` with `MarketDataType.CANDLE`; bar-close is the reference price per the strategy preparation contract), while quote-based paper execution stays explicitly unavailable for candles via a `BLOCKED` disposition instead of synthetic bid/ask. A minimal deterministic `BASIC_BAR` fill model now prices candle MARKET orders at the observed bar close through the existing `FillModel` seam (`CandleFillModel`, routed by `DataAdaptiveFillModel` without changing quote behavior); limit/stop orders propose no fill rather than an inferred one, and all fills remain `SIMULATED_EXECUTION` with explicit assumptions. Each fill proposal now carries its selecting model identity (`QUOTE`/`paper-core-v0.3` or `BASIC_BAR`/`basic-bar-v2`) onto the engine receipt, so mixed quote/candle runs can no longer inherit a misleading profile label; quote receipt metadata is unchanged. Intrabar semantics, partial fills beyond the existing ratio, slippage beyond the existing model, and richer bar-model provenance remain future M3 work. `CandleFillModel` has since grown a conservative close-cross LIMIT rule (`basic-bar-v2`): BUY fills only at or below the limit, SELL only at or above it, priced at the exact bar close, with high/low never triggering fills; STOP/STOP_LIMIT still propose no fill. `CandleFillModel` now classifies stop triggers explicitly (`basic-bar-v3`): a touch confirmed by the close fills at the close, a touch without confirmation is ambiguous and blocked rather than priced, untouched stops rest unfilled, and STOP_LIMIT stays rejected because post-trigger limit ordering is unknowable from OHLC; single-step lifecycle is unchanged. `BacktestResult` now carries experiment-level `BacktestFidelity` reusing the research `ResultQuality` vocabulary (models, evidence types, determinism, limitations) with per-receipt model identity; missing research-provenance inputs remain explicitly unavailable rather than fabricated. `CandleFillModel` (`basic-bar-v4`) accepts an optional Decimal candle-volume participation rate bounding proposed quantity by that share of the observed bar volume (zero volume means no fill); the cap is recorded as a modeled assumption, never observed liquidity, while pricing, triggers, quote behavior, and the existing partial-fill ratio remain unchanged. The pre-existing deterministic `slippage_bps` control is now Decimal-strict at construction, applies unchanged after price discovery (BUY multiplies, SELL divides, per the pinned engine semantics), records a `reference_price=` token only when actually applied, and is noted in backtest fidelity; no new slippage parameter was introduced.

`PendingExecutionRecoveryRunner` remains a deterministic application service with no broker-submit capability. The current hardening branch also makes LIVE execution depend on a started recovery-backed `ApplicationRuntime` and adds submission-time trading-gate authorization spanning durable reservation and the broker call. `ApplicationRuntime` now provides the explicit one-shot startup lifecycle seam: it requires a recovery hook, runs it synchronously before marking the runtime started, rejects repeated starts, and leaves startup failed if recovery infrastructure raises. `ProductionRuntime` now provides the concrete process-composition boundary: it owns the durable SQLite lifecycle, accepts explicit registry configuration, delegates to the recovery-backed `ApplicationRuntime`, and closes persistence on composition failure. It intentionally does not construct credentials, broker transports, or deployment-specific services. Therefore this is validated production composition, not a claim of an executable CLI/service deployment or real-broker end-to-end startup.

The continuation implementation deliberately remains persistence-agnostic: it consumes authoritative receipt/reconciliation contracts and does not introduce a database or broker network dependency by itself.

## Current adversarial findings

The latest review of the 20-commit recovery sequence identified two additional LIVE control-path gaps: startup recovery was not a required dependency of `ExecutionOrchestrator`, and the gate check could race with broker submission. The current hardening branch addresses both. These changes are documented as implementation work pending independent validation; they do not rewrite the earlier historical validation checkpoints.

## Documentation policy

Architecture documents distinguish implemented/current behavior, target architecture, and roadmap/future capabilities. Historical batch records should not be treated as current implementation state unless explicitly marked as historical.

## R1-C9 milestone

R1-C9 multi-instrument account-state synchronization is implemented and merged (squash `53022d15ff9e209e78739c1b87462635a8c2e174`). The final implementation head was `6bf81fb2571da7423e25865b6c859bea6f5e78eb` on `feat/r1c9-remediation`. External OpenCode/local revalidation reported **1185 passed, 0 failed** in the full suite; the focused C9/replay set reported **23 passed**. Changed-file Ruff had **0 new in-scope findings**, strict mypy had **0 errors in the changed production files**, and `git diff --check` passed. C9 adds an explicit `AccountStateSamplingPolicy` (`EXACT_CURRENT` default, `AS_OF_OBSERVED` opt-in) mapped onto the existing tracker behavior, plus a replay-boundary extension so `HistoricalReplay` accepts multiple single-instrument series merged deterministically, while `HistoricalDataSeries` remains strictly single-instrument. No LIVE, broker, reconciliation, recovery, risk, persistence, or accounting semantics were changed.

## R1-C8 milestone

R1-C8 historical account-state valuation provenance is implemented and merged in PR #69. The final revalidated implementation head was `57ddc1e5e65a55e8cea0296e9120b704e9224951`; it was squash-merged to main as `d5a8776d26e773552b1ba072fcffc827176c0183`. External revalidation reported **1175 passed, 0 failed, 0 errors, 1 skipped** in the full suite, with the optional Dhan SDK test skipped; the focused C8/C4/C7 regression set reported **89 passed**. Changed-file Ruff passed with zero new in-scope findings, strict mypy passed for `historical_account_state.py`, and `git diff --check` passed. C8 adds immutable valuation provenance to historical account-state snapshots without changing mark-selection, accounting, risk, LIVE, broker, reconciliation, retry, UNKNOWN, or recovery semantics.

## R1-C7 milestone

R1-C7 time-indexed historical account-state sampling is implemented and merged in PR #67. The final revalidated implementation head was `92f3a7915a70b16f43d98eae8f0ad36d79c3af65`; it was squash-merged to main as `3a35d32ce60eecb155027bb59a69edd94e5b4cff`. External revalidation reported **1173 passed, 0 failed, 0 errors, 1 skipped** in the full suite, with the optional Dhan SDK test skipped; the focused C7/execution/backtest regression set reported **76 passed**. Changed-file Ruff had **0 new in-scope findings**, strict mypy passed on the three changed production files, and `git diff --check` passed. The final implementation adds timestamped valuation marks and an additive pre-frame `account_state_series` with exact-current-mark fail-closed semantics while preserving the C4 receipt-driven `account_states` path. No LIVE, broker, reconciliation, retry, UNKNOWN, recovery, risk, or accounting semantics were changed.

## R1-C6 milestone

R1-C6 execution-fidelity hardening is implemented and merged in PR #65. The final validated implementation head was `5a58318c3978b3a78da32847d717e8bc842a8ac8`; it was squash-merged to main as `8067e5f3b81344698b818d950373bbcc477c170a`. External revalidation reported **1168 passed, 0 failed, 0 errors, 1 skipped** (the optional Dhan SDK test). Changed-file Ruff, strict mypy for the two changed production files, and `git diff --check` all passed. The final C6 implementation touched only the paper/research execution-fidelity path and test/docs surfaces; it did not expand LIVE, reconciliation, retry, UNKNOWN, recovery, broker SDK, persistence, or integration boundaries.

## Current roadmap direction

R1-C1 through R1-C12 are complete. R1-C13 is complete through C13.8. The next engineering milestone is R1-C14.

C14 establishes a deterministic, provider-neutral historical dataset ingestion application boundary that composes the existing `MarketDataPort`, `DatasetCatalog`, historical-data quality, `MarketDataStore`, dataset-backed research access, and research provenance seams. Dataset identity is pre-declared and authoritative; observations remain lossless; completeness remains evidence-bound; persistence semantics remain centralized; and provider-specific behavior remains outside the dataset domain.

The protected C14 salvage sources are `feat/m2-dataset-ingestion-workflow-v1` and `feat/dhan-host-market-data-wiring-v1`. They are not current implementation branches and must not be merged wholesale; their unique tests/design are source material for C14.

C14 explicitly defers scheduling, retry orchestration, streaming, production historical-data service, distributed ingestion, cloud storage, generic ETL, UI, AI/ML, optimization, and broad broker expansion.

GitHub Actions is not a repository validation gate while billing is disabled; OpenCode/local validation remains the execution gate. No production-broker end-to-end execution has been performed.
