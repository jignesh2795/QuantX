---
name: quantx-execution
description: Use when working on QuantX execution integrity — paper trading, order receipts, preconditions, idempotency, reconciliation, pending-order recovery, trading gate, uncertain submissions, partial-fill continuation, ExecutionOrchestrator, startup recovery. Front-load keywords: execution, receipt, reconciliation, recovery, idempotency, fail-closed, paper, trading gate, pending order, submission.
---

# QuantX Execution Integrity & Recovery

Current project focus. All live-path decisions are **fail-closed**: missing/unknown evidence is never converted into approval or a definitive outcome.

## The single execution boundary

`src/quantx/application/execution.py` → `ExecutionOrchestrator.execute()` / `.continue_partial()` is the ONE submission boundary for all modes (backtest/replay/shadow/paper/live). It requires a started `ApplicationRuntime` and trading-gate authorization.

**Never create a second LIVE execution path.**

## Fail-closed transaction boundary

`docs/architecture/43-execution-transaction-boundary.md` and `execution/transactions/coordinator.py`:

```
ApprovedExecutionRequest
  → precondition evaluation (BLOCKED/UNKNOWN = no submit)   [execution/preconditions/]
  → canonical request fingerprint                            [execution/idempotency/fingerprint.py]
  → idempotency check                                        [execution/idempotency/store.py]
  → submission adapter
  → ExecutionReceipt                                         [execution/receipts/]
  → reconciliation
Uncertain submission → Pending idempotency → broker reconciliation
  → definitive evidence → canonical receipt recovery → complete idempotency
```

Key invariant: broker evidence is fetched **outside** the transaction; only final local resolution (receipt save + idempotency resolution) shares one `UnitOfWork` transaction (`application/pending_reconciliation.py`).

## Key modules

| Concern | Path |
|---|---|
| Preconditions (READY/BLOCKED/UNKNOWN) | `execution/preconditions/{evaluator,models}.py` — owns the verdict; integrations only produce *observed evidence* |
| Idempotency | `execution/idempotency/{fingerprint,store}.py`, `persistence/sqlite/idempotency.py` |
| Receipts / lifecycle | `execution/receipts/{models,lifecycle}.py` (`ExecutionReceipt`, `ExecutionLifecycle`) |
| Order lifecycle state model | `execution/order_lifecycle.py` — includes uncertain `UNKNOWN`; deliberately distinct from `receipts/lifecycle.py`, do not merge |
| Trading gate | `execution/trading_gate.py` + `persistence/sqlite/trading_gate.py` — fail-closed authorization spanning reservation → broker call |
| Transaction coordinator | `execution/transactions/coordinator.py` |
| Continuation (partial fills) | `execution/continuation.py` — `ExecutionContinuationService`, persistence-agnostic |
| Dispatch (non-LIVE modes) | `execution/dispatch.py` |
| Post-trade risk/enforcement | `execution/post_trade_risk.py`, `execution/post_trade_enforcement.py` |

## Paper trading (three layers)

> Cash/valuation/P&L/charges knowledge lives in `quantx-simulation-accounting`; this section covers submission and venue semantics only.

1. `execution/paper/` — deterministic venue: `broker.py` (`PaperBroker`), `matching.py` (`PaperMatcher`), `fills.py`, `latency.py`, `order_types.py`, `profile.py`, `evidence.py`, `executor.py`.
2. `execution/paper_engine.py` — legacy flat `PaperExecutionEngine` (re-exported from `execution/paper/__init__.py`).
3. `execution/paper_session.py` — session orchestration: cash ledger + margin ledger + mark-to-market + post-trade enforcement.

App-level: `application/backtest.py` → `DeterministicBacktestService` composes replay + strategy + risk + policy + paper execution + accounting.

Paper contract: **missing required quotes never create invented fills**; repeated client order IDs are idempotent. `PaperMatcher` "never invents market data".

## Reconciliation

Pure comparison — no refresh, no retry, no readiness logic:

- `integrations/reconciliation/{account,orders,positions,broker_evidence}.py` — `AccountReconciler`, `OrderReconciler`, `PositionReconciler`, `BrokerOrderEvidence` (3 distinct lookup outcomes, never conflated).
- `application/reconciliation.py` — `OrderStateReconciliationWorkflow` (conservative aggregate; UNKNOWN stays UNKNOWN).
- `application/evidence_refresh.py` — `ReconciliationEvidenceRefresher` + `DefinitiveEvidencePolicy`.
- `application/not_found_policy.py`, `application/operator_resolution.py` — conservative NOT_FOUND / operator closure for unresolvable PENDING reservations.

Evidence rules (`docs/architecture/47-integration-boundaries.md`): integrations produce **observed evidence only**; missing evidence stays UNKNOWN; routing must never fail over across accounts (`account_id`, `connection_id`, `broker_id`, `market_context_id`).

## Recovery & startup

Startup ordering rule (`docs/architecture/50-production-host-integration-boundary.md`):

```
construct → bind explicit identities → recover pending LIVE state → become ready → permit LIVE submission
```

- `application/pending_recovery.py` — `PendingExecutionRecoveryRunner` / `recover_pending_live_executions()`: boot-time, deterministic, **never submits broker orders**, per-context failure isolation.
- `application/runtime.py` — `ApplicationRuntime.start()`: ONE-SHOT startup recovery before marking started; rejects repeat starts.
- `application/recovery_composition.py` — `build_application_runtime()`, `RecoveryEvidenceFactory`.
- `application/production.py` — `build_production_runtime()`: process boundary owning SQLite lifecycle; no credentials/transports/background workers; `close()` for deterministic shutdown.
- `application/uncertain_submission.py` — `UncertainSubmissionReceiptRecovery`.

**No background recovery daemon. No automatic retry on uncertain broker outcomes** — uncertain → `UNKNOWN` receipt, then reconciliation.

## Testing

```powershell
uv run pytest tests/unit/execution -q
uv run pytest tests/unit/execution/paper -q
uv run pytest tests/unit/application/test_reconciliation_workflow.py -q
```
