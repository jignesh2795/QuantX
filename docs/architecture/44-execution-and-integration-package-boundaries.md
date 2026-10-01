# Execution and integration package boundaries

The execution subsystem is separated conceptually into:

- `execution/`: normalized execution contracts and coordination.
- `execution/preconditions/`: fail-closed readiness checks.
- `execution/idempotency/`: duplicate-submission protection.
- `execution/transactions/`: orchestration of preconditions, idempotency, submission and receipts.
- `execution/receipts/`: immutable execution/audit records.
- `execution/paper.py`: current paper simulator implementation retained during incremental migration.
- `execution/order_lifecycle.py`: current order lifecycle state machine retained during incremental migration.
- `integrations/`: broker/account-specific adapters and reconciliation.

Broker plugins must implement the integration submission contract and return
normalized QuantX execution receipts. Vendor SDK types must remain inside the
plugin boundary.

Migration is incremental: compatibility modules remain in place until callers
have moved to the new package boundaries and tests cover the new imports.
