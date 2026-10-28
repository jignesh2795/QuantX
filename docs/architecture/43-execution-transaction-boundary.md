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
it before any durable reservation or broker contact. The issuer is stored in a module-private
weak registry instead of an `ExecutionOrchestrator` instance attribute. There is no callable
module-level issuance helper; normal issuance occurs inline in `execute` only after the
admission path succeeds. The authorization nonce must be an exact `UUID` before replay/digest
processing, and consumption is atomic.

The token proves issuer binding and single-use request identity; it does not authenticate
risk evidence. Arbitrary evaluator callbacks are rejected. The application-owned
`LivePreTradeRiskEvaluator` reports authoritative evidence unavailable because no trusted
source authenticates positions, balances, P&L, observation time, account identity, or
broker-connection identity. Consequently public LIVE dispatch remains blocked, even after
an operator enables the trading gate, until a trustworthy source is implemented.

This is an application API boundary, not process isolation against arbitrary code executing
inside the same Python interpreter. Issue #267 stays open; no production LIVE readiness
is claimed.
