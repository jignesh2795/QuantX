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

`ExecutionOrchestrator._execute_live_transactional` is the only application-owned LIVE
submission path, and it is entered only from `ExecutionOrchestrator.execute` with a
`LiveSubmissionAuthorization`: a single-use credential minted after every LIVE admission check
succeeded for the exact request (request proofs, resolved product, LIVE prerequisites, trading
gate, market-policy stages, session guard, broker observations, durable unit of work, and
pre-trade risk approval). The credential binds the dispatched `client_order_id` and the
canonical request fingerprint and carries a keyed digest under a per-orchestrator random key
held inside a private `LiveSubmissionAuthorizer`; verification runs before the first durable
read, so a missing, forged, foreign, tampered, mismatched, or replayed credential fails closed
with no reservation and no broker contact. The credential relays admission; it grants no
authority of its own and does not replace the trading gate, which remains the authorization
authority at reservation and submit admission.

The transaction layer does not decide broker-specific rules and does not invent missing account, market, or execution data.
