---
name: quantx-execution
description: Use when working on QuantX execution integrity — paper trading, order receipts, preconditions, idempotency, reconciliation, pending-order recovery, trading gate, uncertain submissions, partial-fill continuation, ExecutionOrchestrator, startup recovery. Front-load keywords: execution, receipt, reconciliation, recovery, idempotency, fail-closed, paper, trading gate, pending order, submission.
---

# QuantX Execution Integrity & Recovery

The safety discipline this skill covers. Active priorities/milestones are authoritative in `docs/STATUS.md` and `docs/roadmap/`. All live-path decisions are **fail-closed**: missing/unknown evidence is never converted into approval or a definitive outcome.

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

## Trading-gate submit admission

`DurableTradingGate` (`execution/trading_gate.py`, SQLite store in `persistence/sqlite/trading_gate.py`):

- `submission_permit()` covers the gate check plus the durable idempotency reservation only. It is released before any broker I/O, so `block()` never waits for a slow broker call.
- `admit_submission()` is the linearization point: it re-checks authorization after the reservation is durable and immediately before `broker.submit()`. A `block()` that returns before admission denies the submission with zero broker contact.
- A `block()` landing after admission does **not** cancel the already-admitted broker operation; the call runs to its genuine broker outcome (never misreported as cancelled or blocked-after-the-fact).
- A denied admission returns `BLOCKED` with the reservation left `PENDING` — never submitted, never uncertain, never auto-retried — for the established reconciliation / operator-resolution path.
- A missing durable state defaults to **disarmed** (`default_enabled=False`) and the default is persisted. A failed `block()`/`enable()` persist latches a process-local fail-closed fault preserving the reason; queries and admission then report blocked without reloading stale enabled state.
- The latch is shared by every gate bound to the same persistence domain (one store object, or one database behind separate store wrappers via `shared_fault_domain`). Independent stores and databases never share faults; there is no global latch. A successfully persisted `block()`/`enable()` on any gate in the domain clears it.
- Process-crash limitation: the latch cannot survive a crash — only successfully persisted state does. Failed-write recovery always needs a later successful persist.
- No gate/store lock is ever held across broker I/O. Lock order is uniformly gate → store.

## Where things live

- Key modules by concern (preconditions, idempotency, receipts, continuation, dispatch, post-trade risk): `references/execution-map.md`.
- Paper venue layers and the paper contract: `references/paper-trading.md`.
- Reconciliation components and evidence rules: `references/reconciliation.md`.
- Startup/recovery runners and composition: `references/startup-recovery.md`.

## Recovery & startup — ordering rule

```
construct → bind explicit identities → recover pending LIVE state → become ready → permit LIVE submission
```

(`docs/architecture/50-production-host-integration-boundary.md`)

- Startup recovery is boot-time, deterministic, and **never submits broker orders**, with per-context failure isolation.
- **No background recovery daemon. No automatic retry on uncertain broker outcomes** — uncertain → `UNKNOWN` receipt, then reconciliation.

## Testing

```powershell
uv run pytest tests/unit/execution -q
uv run pytest tests/unit/execution/paper -q
uv run pytest tests/unit/application/test_reconciliation_workflow.py -q
```
