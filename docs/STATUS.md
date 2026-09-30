# QuantX Status

## Current state
**Phase:** v0.1 implementation / execution-integrity and recovery hardening.

The repository contains an implemented domain, execution, research, India-market, integration, and reconciliation foundation. The active implementation track is execution recovery and continuation safety.

**Last fully validated reference:** `feat/continuation-claim-recovery-state-v1` at `746ed9d37d0922f4eff32822a0f485a31d71e10d`.

## Validation baseline

The last fully validated implementation baseline is **612 passed, 0 failed, 0 errors, 0 skipped** at `746ed9d37d0922f4eff32822a0f485a31d71e10d`.

Post-validation follow-up currently includes LIVE durability hardening and restart coverage on top of that green baseline: LIVE now requires a UnitOfWork-backed transaction path; the margin/replay composition fix remains included; and pending LIVE reservation recovery is covered across a simulated process restart. The current tip requires a fresh local validation run before a new green baseline is claimed.

This is the reported validation result for the checked commit. The available GitHub Actions status endpoint does not show an independent workflow run for `7f73d10`, so this document does not claim GitHub CI independently executed that suite.

Recent continuation/recovery work includes:
- explicit continuation lifecycle reconstruction from authoritative receipt evidence;
- continuation-chain lineage and aggregate fill validation;
- idempotent continuation dispatch claims;
- pending/recoverable/resolved continuation recovery states;
- validation that reused continuation claims match authoritative receipt identity, quantity, account, and broker connection;
- conservative recovery of execution state rather than inference from an uncertain submission.

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

Execution integrity and reconciliation remain the active track. The repository now covers idempotency, execution receipts, order lifecycle reconstruction, account/connection identity, broker-order reconciliation, bounded evidence refresh, uncertain-submission recovery, and partial-fill continuation/recovery.

The continuation implementation deliberately remains persistence-agnostic: it consumes authoritative receipt/reconciliation contracts and does not introduce a database or broker network dependency by itself.

## Documentation policy

Architecture documents distinguish implemented/current behavior, target architecture, and roadmap/future capabilities. Historical batch records should not be treated as current implementation state unless explicitly marked as historical.

## Next direction

Before adding UI, AI, or a broad broker matrix, continue the execution/reconciliation audit and keep the current package boundaries stable. Update canonical documentation whenever a durable architectural boundary or validation baseline changes.

`uv.lock` may remain locally modified by environment operations and is not a project change unless dependencies intentionally change.