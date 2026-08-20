# Execution Reliability Batch

This batch consolidates the execution path around explicit package boundaries.

## Flow

ApprovedExecutionRequest -> execution preconditions -> idempotency -> transaction coordinator -> execution port -> receipt -> reconciliation.

## Package placement

- `execution/preconditions/`: reusable execution gates
- `execution/idempotency/`: duplicate-submission protection
- `execution/transactions/`: orchestration only
- `execution/receipts/`: immutable execution/audit records
- `execution/paper/`: deterministic simulation
- `execution/lifecycle/`: order state machine
- `integrations/execution_adapter.py`: broker-facing bridge
- `integrations/reconciliation/`: broker/account/position reconciliation

## Rule

Unknown broker outcomes are reconciled; they are never silently interpreted as rejected or filled.

The existing compatibility modules remain until their callers are migrated and tests confirm behavior.
