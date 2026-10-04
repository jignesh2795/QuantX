# Control and Safety Path (Draft)

This document describes the intended ordered control path for QuantX execution.

It is adapted from QuantumTrade's multi-layer safety thinking, rewritten for QuantX's current architecture (execution integrity, recovery, trading gates, fail-closed LIVE).

Status: **draft / target with implemented anchors**. Where behavior is already implemented, it is marked. Where it is still partial, that is stated.

---

## Purpose

Make the control path obvious:

- What must happen before a broker submit is allowed
- What is persisted
- What happens on uncertain or failed outcomes
- What recovery is allowed to do (and not do)

Principle: **prefer fail-closed and authoritative evidence over inference**.

---

## Ordered path (conceptual)

```
Strategy / application intent
        |
        v
[1] Domain validation
    - Instrument, side, quantity, order type, account/connection identity
    - Capability checks (adapter/broker supports the requested operation)
        |
        v
[2] Pre-trade risk / policy checks  (partial today)
    - Stateless or narrowly scoped risk decisions
    - Reject without side effects when possible
        |
        v
[3] Trading gate + reservation  (implemented direction)
    - Durable trading-gate authorization
    - Idempotency / pending LIVE reservation context
    - No submit without a started recovery-backed runtime where required
        |
        v
[4] Broker submit (adapter boundary)
    - Only through approved dispatcher/adapter path
    - Direct LIVE dispatcher/adapter bypasses blocked
        |
        v
[5] Receipt capture
    - Durable execution receipt
    - Completed submissions retain a receipt even when idempotency completion is uncertain
    - Broker-returned UNKNOWN remains durably PENDING for reconciliation
        |
        v
[6] Fill / continuation handling
    - Partial-fill continuation and lineage where applicable
    - Continuation claims validated against authoritative receipt identity
        |
        v
[7] Reconciliation and recovery  (strong focus)
    - Reconstruct from authoritative evidence
    - Pending context isolatable per failure
    - Concurrent recovery resolves a pending reservation at most once
    - No broker-submit capability inside pure recovery runners
        |
        v
[8] Portfolio / position state update
    - Driven by accepted evidence, not guessed outcomes
```

---

## Layer notes

### 1. Domain validation

Core domain contracts should reject invalid intents early.

Adapters must not be the first place basic identity and capability rules are enforced.

### 2. Pre-trade risk / policy

Target: keep risk decisions explicit and testable.

Avoid turning this into a full retail "safety product." Prefer clear contracts that plugins or hosts can extend.

### 3. Trading gate + reservation

Implemented direction in current STATUS:

- Durable trading-gate state
- Versioned pending LIVE execution context with idempotency reservations
- LIVE execution depends on recovery-backed application runtime startup where required
- Submission-time authorization spanning reservation and broker call

### 4. Broker submit

Adapter boundary only.

Production host composition (e.g. Dhan host slice) should construct credentials/transport and register identity without inventing new execution semantics in the host layer.

### 5. Receipt capture

Receipts are the source of truth for what was submitted and what the system believes happened.

UNKNOWN outcomes stay pending for reconciliation rather than being completed optimistically.

### 6. Fill / continuation

Continuation must be identity-bound (receipt, quantity, account, connection).

Reuse of claims must match authoritative evidence.

### 7. Reconciliation and recovery

Recovery is conservative:

- Reconstruct from evidence
- Isolate malformed contexts
- Do not invent fills or completions
- Pure recovery services should not submit to brokers

Startup recovery should be an explicit one-shot lifecycle step before the runtime is marked started.

### 8. Portfolio / position updates

State changes should follow accepted domain events / receipts.

Do not advance portfolio state on uncertain submissions.

---

## Research / paper path alignment

Backtest and paper paths should reuse the same domain meaning where practical.

Fill models must remain explicit:

- Model identity recorded on receipts where applicable
- Limitations and assumptions visible in fidelity reporting
- No synthetic bid/ask invented to force quote semantics onto candle data

Blocked dispositions are preferable to hidden approximations.

---

## Non-goals for this document

- Defining a full strategy product workflow
- Defining notification channels
- Defining a multi-broker UI
- Claiming end-to-end production-broker execution that has not been validated

---

## Related documents

- `docs/STATUS.md` — implemented recovery and LIVE-control evidence
- `docs/planning/quantumtrade-transfer-map.md` — what was taken from QuantumTrade
- `VISION.md` — core vs plugin boundary
- Production host integration boundary docs under `docs/architecture/`
