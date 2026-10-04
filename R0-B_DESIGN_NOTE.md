# R0-B Design Note: Bounded Dhan Timeouts & Kill-Switch Latency

## 1. Gate-lock scope

**Current:** `TradingGate.submission_permit()` (and `DurableTradingGate.submission_permit()`) holds the lock for the entire duration including the broker `submit()` call. The lock is an `RLock` (in-memory) plus for `DurableTradingGate` a database lock via `state_store.synchronize()`.

**Change:** The lock is acquired only for:
- Checking gate state (`enabled`)
- Creating the durable PENDING reservation (inside UnitOfWork Scope A)

The lock is released **before** the broker `submit()` call. The `submission_permit()` context manager yields `True`/`False` for authorization; the broker call happens after the `with` block exits.

**TOCTOU safety:** The gate check and reservation creation remain atomic under the lock. If the gate is blocked at check time, no reservation is created. If the gate is blocked after the permit exits but before/during the broker call, a PENDING reservation already exists (authorized when gate was open). This is safe: the order was authorized, the reservation is durable, and reconciliation will resolve the outcome.

`block()` can now acquire the lock immediately because it no longer waits for an in-flight broker call.

## 2. Persistence-lock scope

**Unchanged:** `_execute_live_transactional()` already separates:
- Scope A (UnitOfWork): inspect idempotency → create PENDING reservation → commit
- Broker call: **outside** any transaction
- Scope B (UnitOfWork): persist receipt → complete idempotency → commit

The SQLite transaction is never held across the network call. No regression.

## 3. Broker-call timeout boundary

**New:** Explicit timeout configuration at the Dhan host/transport boundary.

- `DhanHostConfig` gains required `submit_timeout_seconds: float`, `cancel_timeout_seconds: float`, `reconcile_timeout_seconds: float` fields (no defaults for LIVE).
- `DhanTransport` protocol methods `submit`, `cancel`, `reconcile` gain a `timeout: float` parameter.
- `DhanSDKTransport` enforces timeout via `concurrent.futures.ThreadPoolExecutor` with `future.result(timeout=...)`. The underlying SDK call runs in a worker thread; on timeout, the future is cancelled (best-effort) and a `DhanTimeoutError` is raised.
- `InMemoryDhanTransport` accepts the timeout parameter but ignores it (tests control latency via a `SlowTransport` test double).
- Timeout exceptions are caught in `DhanBrokerAdapter.submit/cancel/reconcile` and normalized to `ExecutionOutcome.UNKNOWN` receipts. Vendor SDK exceptions never leak past the adapter boundary.

## 4. Timeout classification

- **Timeout** = `UNKNOWN` / unresolved outcome. Never `REJECTED`.
- No automatic retry, no automatic resubmission.
- Durable PENDING reservation remains; reconciliation required.
- Idempotency key (`client_order_id` + fingerprint) prevents duplicate submission: a later reconciliation or manual retry will see the existing PENDING reservation and not submit again.

## 5. Idempotency after timeout

- PENDING reservation is created in Scope A (before broker call).
- If broker call times out: Scope B is skipped; PENDING remains incomplete.
- Recovery/reconciliation will re-observe broker state and complete the reservation.
- `client_order_id` fingerprint binding ensures the same request cannot be submitted twice.

## 6. `trading_gate.block()` behavior

- Acquires the same lock that `submission_permit()` uses.
- Since the lock is no longer held during the broker call, `block()` returns immediately (bounded by in-process lock contention only).
- Any in-flight broker call continues to completion (or timeout) independently; its result is saved in Scope B if it finishes, or left as PENDING for reconciliation if it times out.

## 7. Slow broker call that eventually succeeds after timeout boundary

- The adapter's `submit()` raises `DhanTimeoutError` → normalized to `UNKNOWN` receipt.
- The broker may still process the order asynchronously.
- Reconciliation (manual or automated) will later observe the final state and complete the reservation.
- No duplicate submission: the PENDING reservation blocks re-submission of the same `client_order_id` + fingerprint.

## 8. Why duplicate submission cannot be introduced

- Idempotency store checks `client_order_id` + fingerprint **before** any submission (Scope A).
- If a PENDING reservation exists, `reserve_or_get` returns `reservation_pending=True`, `reservation_acquired=False` → orchestrator returns `UNKNOWN` without calling broker.
- Timeout path does not call `complete()` or `resolve_pending()`; the PENDING row remains.
- Any subsequent attempt with the same `client_order_id` + fingerprint hits the same check and does not submit.

---

## Configuration Contract

| Field | Required for LIVE | Default |
|-------|-------------------|---------|
| `submit_timeout_seconds` | Yes | None (fail-closed if missing) |
| `cancel_timeout_seconds` | Yes | None |
| `reconcile_timeout_seconds` | Yes | None |

Invalid values (≤ 0, non-numeric) raise `ValueError` at `DhanHostConfig.__post_init__` — fail-closed at startup.

---

## Files to Change

1. `src/quantx/plugins/dhan/host.py` — add timeout fields to `DhanHostConfig`, validate, pass to transport
2. `src/quantx/plugins/dhan/transport.py` — add `timeout` param to `DhanTransport` protocol methods; implement timeout wrapper in `DhanSDKTransport`; add `DhanTimeoutError`
3. `src/quantx/plugins/dhan/adapter.py` — pass timeout from config to transport calls
4. `src/quantx/execution/trading_gate.py` — (no change needed; lock scope is controlled by caller)
5. `src/quantx/application/execution.py` — move `broker.submit()` outside `submission_permit()` block in `_execute_live_transactional`
6. Tests — new regression tests for gate latency, timeout semantics, config validation