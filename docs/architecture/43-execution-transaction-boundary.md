# Execution Transaction Boundary

QuantX execution is organized as a transaction boundary rather than a direct broker call.

```text
ApprovedExecutionRequest
        |
        v
Precondition evaluation
        |
        +--> BLOCKED / UNKNOWN -> no submission
        |
        v
Canonical request fingerprint
        |
        v
Idempotency check
        |
        +--> existing receipt -> duplicate submission suppressed
        |
        v
Submission adapter
        |
        v
ExecutionReceipt
        |
        v
Position / order reconciliation

Submission uncertain
        |
        v
Pending idempotency
        |
        v
Broker reconciliation
        |
        v
Definitive broker-order evidence
        |
        v
Canonical receipt recovery
        |
        v
Complete idempotency
```

## Package boundaries

- `execution/preconditions/`: fail-closed checks before submission.
- `execution/idempotency/`: request identity and duplicate suppression.
- `execution/receipts/`: immutable receipt records and uncertainty semantics.
- `execution/accounting.py` and `execution/cash_ledger.py`: fill application is idempotent by `execution_id`; conflicting reuse of a fill identity is rejected so replay/recovery cannot double-apply state.
- `execution/transactions/`: orchestration only; vendor-specific behavior stays in adapters.
- `application/live_submission_capability.py`: single-use LIVE submit admission authorization (below).
- `application/uncertain_submission.py`: conservative receipt reconstruction after definitive broker-order evidence.
- `integrations/`: broker/account/venue adapters and operational state.

## LIVE submit admission authorization

The transactional path requires a single-use `LiveSubmissionAuthorization` and validates
it before any durable reservation or broker contact. The issuer is kept in a module-private
weak registry keyed by the orchestrator rather than an instance attribute, so ordinary callers
cannot obtain a genuine token by inspecting an `ExecutionOrchestrator` instance. The token
binds the client-order UUID and canonical request fingerprint; UUID fields are validated by
exact runtime type before digest or consumed-set processing, and consumption is atomic.

This is an application API boundary, not process isolation against arbitrary code executing
inside the same Python interpreter. HMAC integrity proves the token was issued by that
issuer; it does not prove risk data is authoritative or that a caller-provided risk callback
is trustworthy.

**Issue #267 remains open:** `LiveRiskEvaluationInputs` must match the exact order and
execution context, and the repository still lacks a demonstrated production risk-evidence
source for positions, balances, P&L, account/connection identity, and observation-time
provenance. Request matching is necessary but not sufficient evidence authority. No LIVE
readiness claim is made while that source and the supported composition contract remain
unresolved.
