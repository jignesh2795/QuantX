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
```

## Package boundaries

- `execution/preconditions/`: fail-closed checks before submission.
- `execution/idempotency/`: request identity and duplicate suppression.
- `execution/receipts/`: immutable receipt records and uncertainty semantics.
- `execution/transactions/`: orchestration only; vendor-specific behavior stays in adapters.
- `integrations/`: broker/account/venue adapters and operational state.

The transaction layer does not decide broker-specific rules and does not invent missing account, market, or execution data.
