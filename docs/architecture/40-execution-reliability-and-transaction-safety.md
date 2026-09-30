# Execution Reliability and Transaction Safety

QuantX treats order submission as an uncertain distributed operation.

## Batch implementation plan

The execution reliability layer is intentionally implemented as one coherent slice:

1. Idempotency and duplicate-submission protection.
2. Immutable execution receipts with broker provenance.
3. Account/position/connection execution preconditions.
4. UNKNOWN outcome handling followed by reconciliation rather than inference.
5. Paper/live semantic parity tests.
6. Reconciliation-driven recovery for partial fills, cancellations, replacements, and uncertain submissions.
7. Audit events linking request, client order ID, broker order ID, receipts, and final position state.

## Core rule

A network response is evidence about a submission attempt, not proof of final broker state.

For LIVE execution, durable idempotency state is mandatory at the application boundary. The canonical `ExecutionOrchestrator` rejects LIVE execution when no `UnitOfWork` is configured, preventing a process restart from losing a PENDING reservation and permitting duplicate submission.

When the broker outcome is uncertain, QuantX records `UNKNOWN` and reconciles. It never invents `REJECTED`, `ACCEPTED`, or `FILLED`.

## Uncertain-submission receipt recovery

After reconciliation obtains a definitive broker-order observation, the recovery boundary may reconstruct an `ExecutionReceipt` from the canonical `Order`. It is deliberately conservative: broker order identity and requested quantity must match; only definitive lifecycle states are recoverable; filled and partially filled states require real broker `Fill` evidence; fill quantities must agree with the broker observation; and no fill price, quantity, broker status, or receipt state is inferred. Unresolved lifecycle states never create receipts.

## Account safety

Retries and failover must preserve account identity, connection identity, market context, instrument, side, quantity semantics, and execution policy. A retry that would change any of those dimensions requires an explicit higher-level decision.

## Balance policy

No universal minimum capital is assumed. Execution uses fetched broker state or explicitly configured paper/replay state. Broker-specific minimums are treated as versioned venue rules when explicitly supplied.
