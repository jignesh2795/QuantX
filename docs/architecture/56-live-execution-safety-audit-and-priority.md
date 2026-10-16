# LIVE Execution Safety Audit and Remediation Priority

**Status:** Active audit / remediation plan (2026-10-16)

**Current source reviewed:** `main` at `2ce04cf40952124e8b2ef0414cbc4ded9d660292`

**Earlier comparison base:** `bd5045ab6fa81c7ca6fb4503116a7ef12695adf5`

**Tracker:** [#207 — QuantX adversarial code review](https://github.com/jignesh2795/QuantX/issues/207)

## Executive decision

The consolidated Claude Sonnet audits should change execution order. **Do not start package-boundary refactoring or continue lower-priority API/market-realism work while the newly identified LIVE admission, startup-readiness, and post-submit evidence gaps remain unaddressed.** First land deterministic regression tests for the three P0 slices, then fix each slice in isolation and validate at the exact final commit.

The source spot-check was performed against current `main` at the SHA above, not only against the earlier `bd5045a` base. It confirms several critical control-flow shapes. The two failure-injection reproductions (F1 and F2) were reported by the first audit; they were **not rerun by this documentation pass**. Claims below distinguish source-confirmed behavior, audit-reported reproductions, and findings that still require broader evidence.

No LIVE-readiness claim is made. The presence of a `BrokerPort`, a `LIVE` enum value, or a manually assembled `ExecutionOrchestrator` does not establish a production-safe LIVE composition.

## Evidence classification

- **Source-confirmed:** directly observed in current source at `2ce04cf` and linked to the relevant function or contract below.
- **Audit-reported reproduction:** failure injection or test output supplied by one of the two audits; the reproduction has not been independently rerun in this review.
- **Partially verified / needs bounded audit:** the finding is plausible or partly confirmed, but the relevant builder, all call sites, schema path, or source-tree-wide absence has not yet been independently enumerated. Do not present these as established defects until the stated check is complete.

## P0 — Fix the execution safety boundary first

### P0.1 — Durable kill-switch failure and submission admission race

**Source-confirmed at current main**

- `src/quantx/execution/trading_gate.py::DurableTradingGate.block` persists the disabled state before updating the local state. If `state_store.save()` raises, the local update is not performed.
- `DurableTradingGate.allow()` reloads persistent state. If a failed block write leaves an older persisted enabled state, a subsequent `allow()` can read that enabled state.
- The default for both the process-local gate and durable gate is enabled; `DurableTradingGate.__init__` currently declares `default_enabled=True`.
- `src/quantx/application/execution.py::ExecutionOrchestrator._execute_live_transactional` holds `submission_permit()` while it creates the durable PENDING reservation, exits the permit, and only afterward calls `broker.submit()`. Thus reservation admission and actual beginning of the external call are not one gate-protected interval. The source comments deliberately allow `block()` not to wait for a slow broker call, but the current interval also creates a window where a not-yet-started order can reach `broker.submit()` after the gate has been blocked.

**Audit-reported reproduction**

The first audit reports a reproduced sequence where a durable gate's `block()` raises `OSError`, followed by `allow() == True` and a granted submission permit. This exact injection still needs to be added/rerun against the current base.

**Required invariant**

A failed persistence operation must never leave the process permissive. Once `block()` returns, no submission that has not already crossed a clearly defined submit-start boundary may begin. Any already in-flight submit stays explicitly in flight/uncertain; the kill switch cannot undo a call that the broker may have received.

**Remediation:** [#239](https://github.com/jignesh2795/QuantX/issues/239). Its tests must cover state-write failure, missing/corrupt durable state, initially disarmed startup, the reservation-to-submit interleaving, and restart behavior. Preserve the explicit separation between the submit lane and risk-reducing cancellation; do not solve the race by claiming that an in-flight call has been cancelled.

### P0.2 — Startup ignores a non-raising recovery report

**Source-confirmed at current main**

`src/quantx/application/runtime.py::ApplicationRuntime.start` calls the configured `StartupRecoveryHook.run()` and sets `_started = True` whenever that call returns. It does not inspect the returned `PendingRecoveryRun` counters. `src/quantx/application/pending_recovery.py::PendingExecutionRecoveryRunner.run` intentionally isolates per-record failures as result records, so recovery can return normally while one or more submissions remain unresolved.

The current `tests/unit/application/test_runtime.py` includes a recovery-hook exception case, but the checked test names do not include a returned report with unresolved `pending` or `failed` records. Those are different paths: the former already leaves the runtime unstarted; the latter is the reported gap.

**Required invariant**

LIVE readiness requires a completed recovery report with no unresolved or failed required record. A report containing UNKNOWN/pending state, per-record error, malformed context, or non-definitive outcome must leave the runtime unstarted and must be retained for operator diagnosis. Do not infer rejection, retry an order, or erase the evidence.

**Remediation:** [#240](https://github.com/jignesh2795/QuantX/issues/240). Add tests for pending-only, failed-only, mixed resolved/unresolved, and all-definitive reports. Recovery policy and any explicit operator remediation must remain observable and must not bypass the durable reservation.

### P0.3 — Post-submit persistence exceptions and non-authoritative receipt evidence

**Source-confirmed at current main**

`src/quantx/application/execution.py::ExecutionOrchestrator._execute_live_transactional` commits the PENDING reservation before the broker call. It catches exceptions from `broker.submit()` and returns UNKNOWN, but the later `unit_of_work.receipts.save(receipt)` call is outside that submit-exception handler. If persistence raises after the broker accepted, the exception can escape the public execution call while the reservation remains PENDING.

The same code validates a non-UNKNOWN receipt before authoritative persistence. On identity violation, it returns UNKNOWN with a reason but does not return or durably retain that receipt on this path. A receipt whose outcome is UNKNOWN is returned on `ExecutionResult.receipt`, but is not persisted in the authoritative receipt store. Therefore the second audit's phrase “discarded/lost” needs this precision: a returned UNKNOWN object may still be visible to the immediate caller, while the current code does not durably preserve it through the canonical receipt store; a mismatched receipt is discarded from this path altogether.

**Required invariant**

Once the external submit may have occurred, later receipt-storage/serialization/transaction failures cannot escape as though execution outcome were known. Return an explicit UNKNOWN/unresolved result, preserve the PENDING reservation, and surface a durable, non-authoritative evidence trail whenever possible. Invalid or foreign receipts must never complete idempotency, become canonical receipts, or affect accounting, but their broker identity/correlation evidence must not be silently lost.

**Remediation:** [#241](https://github.com/jignesh2795/QuantX/issues/241). Add separate tests for receipt-save failure, idempotency-completion failure, mismatched receipt quarantine, UNKNOWN receipt retention, and restart/reconciliation. Maintain the distinction between **authoritative receipts** and **quarantined observations**; do not solve this by persisting invalid receipts as canonical.

## P1 — Close request authorization and lifecycle gaps

### Approval is not bound to the approved request

**Source-confirmed at current main**

`src/quantx/domain/execution_request.py::ApprovedExecutionRequest.__post_init__` verifies that `risk_result.decision is RiskDecision.APPROVE`, and checks LIVE connection/policy presence. The request type does not bind that approval to a canonical request fingerprint, a resolved risk snapshot identity, or the evaluation timestamp. An approval object can therefore be reused/assembled without evidence in the value that it was evaluated for those exact request semantics and that evidence cut.

**Required direction:** either bind approval to a canonical request fingerprint plus risk evidence/snapshot identity and `evaluated_at`, or move authoritative LIVE evaluation behind a composition boundary that owns the evaluator and approved-request creation. A boolean/enum stamp alone is not an approval capability. Add negative tests for altered quantity, side, instrument, account, market, and stale/different snapshot after approval.

### Optional LIVE guards and no mandatory composition boundary

The current orchestrator permits `live_risk_evaluator` and `session_guard` to be absent from its composition; the LIVE-risk check only runs when an evaluator is supplied. `RiskLimits` fields default to `None`, so construction alone does not establish a non-open risk policy. The audit reports that no supported production LIVE composition is provided under `src/`; this needs a bounded source-tree/call-site confirmation in the implementation PR before being described as a proven total absence.

**Required direction:** define one explicit LIVE composition/factory that requires durable gate state, recovery-backed startup, a risk evaluator with non-empty required limits, current position/account/market evidence, a session guard, identity-bound approved requests, durable persistence, and reconciliation wiring. Missing required configuration must fail construction/readiness, not degrade to optional protection. Do not enable LIVE by introducing a convenience factory that omits a guard.

### F6 — Local preflight rejection is conflated with ambiguous external submission

**Source-confirmed at current main**

`DhanBrokerAdapter.submit()` performs connection, canonical-instrument, market and order-request mapping checks before calling the transport. The orchestrator currently catches a broad exception from `broker.submit()` and returns UNKNOWN for all such exceptions. The adapter contract does not give the orchestrator a typed distinction between a definite pre-I/O rejection and an ambiguous failure after a submit may have reached the broker.

**Required direction:** introduce a typed, trusted boundary distinguishing `NOT_SUBMITTED`/preflight failure from `SUBMISSION_UNKNOWN` after the external call may have started. A definitely-not-submitted request must not look like a possible broker order indefinitely; an ambiguous external result remains UNKNOWN and must not be retried automatically. This is a separate test/fix slice after P0.1–P0.3.

### F7 — Idempotency does not deduplicate rebuilt strategy intent

**Source-confirmed behavior; policy decision still required**

`TradeIntent.intent_id` and `Order.client_order_id` are UUID defaults. Current request idempotency protects repeated requests carrying the same client order ID and fingerprint, but a rebuilt intent/order after restart can get a new identity. That does not necessarily mean every strategy intent must be exactly-once: the project must first define which strategy/event identity is intended to deduplicate a signal, how that identity survives replay/restart, and how a new deliberate attempt differs from a retry. Do not conflate a new order with an uncertain submission retry.

## P1/P2 — Risk semantics and risk-reducing operations

### Reduce-only, flatten and kill-trigger policy

The second audit reports no `cancel-all`, `flatten`, or `reduce-only` path under `src/`. This is a source-tree-wide absence claim and remains an audit-reported finding until a targeted search and capability/call-site inventory are attached. If confirmed, the lack matters: a kill switch that blocks new orders must not imply it can reduce existing exposure, while a blanket gate may block a desired exit as well as a new entry.

**Required direction:** design risk-reducing operations as a separately authorized capability with strict position/account/connection binding, close-only quantity limits and audit evidence. It must not become a way to bypass ordinary identity, market, broker, session, or uncertain-outcome checks. Define explicit trip triggers and post-trip behavior before implementation; do not introduce automatic flattening or compensating trades without a separate risk/recovery decision.

### Daily-loss and gross-versus-net exposure

**Source-confirmed:** `src/quantx/domain/risk.py::evaluate_with_limits` checks `snapshot.daily_pnl` with a comment explicitly stating only already-realized daily P&L counts. It separately checks `equity`/high-water mark for configured drawdown limits. An unrealized-loss trip policy is not currently equivalent to the daily-realized-loss check.

**Partially verified:** pre-trade position and portfolio calculations use the signed projection `current + signed`, then take its absolute value for the configured limit. The second audit reports post-trade enforcement uses gross exposure, but did not verify what the current snapshot builder supplies as `current_portfolio_exposure`. Do not label a net-versus-gross inconsistency proven until that producer path is traced to its canonical position/valuation facts.

**Required direction:** define risk-limit names and snapshot fields unambiguously as signed net, gross absolute, instrument gross, portfolio gross, realized P&L, unrealized P&L, equity/drawdown, and as-of/evidence freshness as appropriate. Make pre-trade and post-trade consumers use the same declared quantity definition. Add hedged-book and mark-to-market loss tests; do not silently redefine the existing fields.

### Ongoing reconciliation and process ownership

- The current `ApplicationRuntime` documentation explicitly says it owns one-shot startup orchestration and has no background worker. The second audit reports no ongoing reconciliation worker. These are consistent: startup recovery alone cannot detect every UNKNOWN or position drift that occurs during a long session. A periodic reconciliation worker is a later design slice with bounded polling, evidence-age policy, duplicate/idempotency safety, and lifecycle ownership; it must not resubmit orders.
- `src/quantx/persistence/sqlite/database.py::SqliteDatabase` documents a single-connection, single-process, multi-thread target and no multi-process support. This is source-confirmed. The audit's OS file-lock recommendation is a possible future mitigation, not an implemented guarantee; first decide whether multiple LIVE processes against one DB are unsupported by invariant or will be prevented by a process lock.
- The audit reports that `DurableTradingGate.load()` takes a write lock, and that SQLite schema migration steps are not transactional/backup-safe. These require targeted current-main inspection and failure-injection/migration-rollback tests before assigning implementation scope; do not change database locking or migration semantics merely from summary prose.

## P2/P3 — Determinism, layering, coverage and release hygiene

### Layering and module boundaries

Current `src/quantx/ports/broker.py` imports `quantx.execution.ports.ExecutionReceipt` as well as integration broker contracts, supporting the reported dependency-direction concern. The second audit reports a broader `ports ↔ execution ↔ integrations` package cycle and notes there is no explicit import-graph regression test. QX-07/#181 already tracks contract ownership and package cycles and is sequenced after QX-04/#193 and QX-05/#194. Do not flatten the graph before the canonical receipt/request/product/contract ownership decisions are settled. When it is time, add an explicit allowed-edge matrix and deterministic import-graph test; do not duplicate contracts into a generic shared package without a semantic owner.

### Dhan submit/cancel execution lane

**Source-confirmed:** `src/quantx/plugins/dhan/transport.py` uses a single-worker `_submit_executor` for both SDK submit and cancellation, while reconciliation has a separate executor. A blocked submit can therefore hold up a later cancel in the shared lane. Introduce a separately bounded/serialized cancellation lane only after testing the vendor SDK's concurrency requirements; preserve per-operation timeout and correlation semantics. Reconciliation must continue to be schedulable even when submission or cancellation is hung.

### Wall clock and random identity

The existing time-source inventory `docs/architecture/53-deterministic-time-source-inventory.md` is explicitly a historical baseline with a scoped M4.1 addendum, not a fresh complete scan of every call site. The audit reports remaining wall-clock and `uuid4` leaks, including pending-recovery ordering that depends on `created_at`. Treat the reported time/order paths as candidates for an exact-current-main AST/call-site audit. Do not mechanically replace intentional transport/audit time or globally remove UUID defaults; distinguish replay/event time, injected operation time, identity policy, and legitimate live-observation timestamps.

### Validation and count reconciliation

The compared audits quote results at different revisions and environments:
- the second audit reports **1,901 passed and 1 skipped** at `bd5045a`;
- older `docs/STATUS.md` entries report **1,713 passed** in an earlier validation record;
- the recent QX-08 exact-feature-head report records **2,027 passed, 1 skipped** at `9bd0d0e` (with 2,028 collected).

These are not comparable until their exact SHA, optional-Dhan-extra state, command scope, and environment are recorded together. `docs/STATUS.md` also contains a stale QX-08 “next step is acceptance-matrix reconciliation” paragraph below the completed closeout section; that instruction must be corrected to avoid reopening completed work. The latest local count in this note is not asserted to be a fresh full-suite run at current `main`.

`.github/workflows/test.yml` exists and declares push/PR triggers. The repo policy says GitHub Actions is not the validation gate while runner/billing conditions are unresolved. Presence of a workflow file is configuration, not evidence it executed. The maintainer decision is whether to disable or retain the workflow as inert configuration; do not claim CI passed without actual executable workflow steps.

## Ordered remediation plan

The order below resolves the merged audits into narrow slices. Each numbered source-fix slice begins with failing regression tests at an exact base SHA, then its behavior change, then the same tests and full local gates at the final SHA.

1. **P0.1 — durable kill-switch.** Add red tests for persistence-write fail-open, initially-enabled default, and a submit-vs-block interleaving. Fix in [#239](https://github.com/jignesh2795/QuantX/issues/239).
2. **P0.2 — startup readiness.** Add red tests for pending/failed return reports (not only raised exceptions); make readiness false until every required recovery result is definitive. Fix in [#240](https://github.com/jignesh2795/QuantX/issues/240).
3. **P0.3 — post-submit evidence.** Add red tests for receipt persistence failure, mismatched/UNKNOWN receipt retention without authoritative completion, and restart/reconciliation. Fix in [#241](https://github.com/jignesh2795/QuantX/issues/241).
4. **LIVE composition and approval binding.** Make required evaluator, limits, session, gate, persistence, recovery and evidence-cut requirements mandatory; bind the approval to request identity/fingerprint and evaluation evidence before any submit.
5. **Risk-reducing operations.** Define reduce-only/cancel-all/flatten semantics, policy triggers and safe behavior after a risk trip. Do not treat this as permission to make compensating orders automatically.
6. **Ongoing reconciliation.** Add a bounded periodic reconciliation lifecycle for mid-session UNKNOWNs and position/account drift, with no auto-resubmit.
7. **Preflight/identity determinism.** Distinguish definitely-not-submitted local failures from ambiguous external calls; then settle strategy-intent identity and pending-recovery deterministic ordering.
8. **Layering and platform gaps.** After QX-04/#193 and QX-05/#194 contract ownership, continue QX-07/#181 with the import graph. Then measured package coverage (#182), API/clock/charges/money work, Dhan transport coverage, conformance schemas, and release/onboarding hygiene.

The comparison supplied refers to an **F3** item in the first-audit priority list without restating that finding's exact invariant or reproducer. Do not guess what F3 means or silently fold it into P0.1; link the original first-audit record and add its concrete failing test before assigning its remediation.

## Cross-cutting acceptance rules

- Treat every result as tied to an exact commit; do not substitute a green test count from another SHA/environment.
- Report focused regressions, full `pytest`, Ruff check and format, strict mypy both with Dhan extra enabled/disabled, locked sync, and `git diff --check`.
- Keep failure-injection evidence separate from source inspection and reviewer/auditor reports.
- A receipt with invalid identity or UNKNOWN status is not authoritative order/accounting evidence; nevertheless retain non-authoritative evidence for reconciliation so the broker correlation/order ID is not silently lost.
- Never automatically retry uncertain submit, infer a rejection from a timeout, or claim an order was cancelled simply because the gate blocked future submission.
- No production broker/LIVE transaction is permitted for these regression tests. GitHub Actions initialization or runner errors are not test results.
- Preserve local operator state. Any validation must run in a disposable detached worktree at the exact SHA; do not change the user's primary checkout, existing worktrees, untracked files, or stashes.

## Relationship to existing work

- QX-01/#191, QX-02/#185, QX-03/#192 and QX-09/#197 remain complete according to their recorded issue/PR evidence; this audit does not reopen them without a concrete new regression.
- QX-08/#196 is closed and acceptance traceability is recorded in the top of `docs/STATUS.md`; remove stale lower-page “next step” text rather than reopening it.
- QX-04/#193 and QX-05/#194 have accepted design decisions in ADR-011/ADR-012 but their implementation issues remain open. Defer QX-07/#181's source package moves until those request/contract ownership decisions are implemented.
- QX-06/#195 is closed for design only under ADR-010; multi-leg implementation remains gated on canonical leg semantics and aggregate risk/persistence support.
- This audit is a triage and acceptance contract, not an implementation-validation report. The three P0 issues above are open; no code fix or current-main test pass is claimed by this document.
