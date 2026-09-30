# QuantX Status

## Current state
**Phase:** v0.1 implementation / execution-integrity and recovery hardening.

The repository contains an implemented domain, execution, research, India-market, integration, and reconciliation foundation. The active implementation track is execution recovery and continuation safety.

**Last fully validated reference:** `feat/continuation-claim-recovery-state-v1` at `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c`.

## Validation baseline

The current fully validated test evidence is **635 passed, 0 failed, 0 errors, 0 skipped** at `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c`.

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

Execution integrity and reconciliation remain the active track. The repository now covers idempotency, execution receipts, order lifecycle reconstruction, account/connection identity, broker-order reconciliation, bounded evidence refresh, uncertain-submission recovery, partial-fill continuation/recovery, durable trading-gate state, durable pending LIVE execution context, malformed-context isolation, explicit recovery-backed application startup, and fail-closed handling of broker-returned UNKNOWN LIVE receipts.

`PendingExecutionRecoveryRunner` remains a deterministic application service with no broker-submit capability. `ApplicationRuntime` now provides the explicit one-shot startup lifecycle seam: it requires a recovery hook, runs it synchronously before marking the runtime started, rejects repeated starts, and leaves startup failed if recovery infrastructure raises. The repository still does not contain a concrete production process entrypoint that constructs the runtime and wires real broker/account/position providers, so this is a validated lifecycle contract rather than a claim of end-to-end deployed startup wiring.

The continuation implementation deliberately remains persistence-agnostic: it consumes authoritative receipt/reconciliation contracts and does not introduce a database or broker network dependency by itself.

## Documentation policy

Architecture documents distinguish implemented/current behavior, target architecture, and roadmap/future capabilities. Historical batch records should not be treated as current implementation state unless explicitly marked as historical.

## Next direction

Before adding UI, AI, or a broad broker matrix, keep the current package boundaries stable and finish the final adversarial review of the LIVE/recovery boundary. The remaining work is primarily integration-level: define the concrete production startup composition for broker, local-position, local-account, and provider resolution dependencies; verify startup behavior across the actual application process lifecycle; and perform a fresh adversarial review of all compatibility/legacy routes that could reach broker transport.

`uv.lock` may remain locally modified by environment operations and is not a project change unless dependencies intentionally change. GitHub Actions runs observed for this branch fail before executing workflow steps, so they are not treated as code-validation evidence.
