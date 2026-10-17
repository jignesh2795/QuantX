# Execution Key Modules (quantx-execution)

| Concern | Path |
|---|---|
| Preconditions (READY/BLOCKED/UNKNOWN) | `execution/preconditions/{evaluator,models}.py` — owns the verdict; integrations only produce *observed evidence* |
| Idempotency | `execution/idempotency/{fingerprint,store}.py`, `persistence/sqlite/idempotency.py` |
| Receipts / lifecycle | `execution/receipts/{models,lifecycle}.py` (`ExecutionReceipt`, `ExecutionLifecycle`) |
| Order lifecycle state model | `execution/order_lifecycle.py` — includes uncertain `UNKNOWN`; deliberately distinct from `receipts/lifecycle.py`, do not merge |
| Trading gate | `execution/trading_gate.py` + `persistence/sqlite/trading_gate.py` — disarmed default, permit-then-admit authorization, domain-shared fail-closed fault latch |
| Transaction coordinator | `execution/transactions/coordinator.py` |
| Continuation (partial fills) | `execution/continuation.py` — `ExecutionContinuationService`, persistence-agnostic |
| Dispatch (non-LIVE modes) | `execution/dispatch.py` |
| Post-trade risk/enforcement | `execution/post_trade_risk.py`, `execution/post_trade_enforcement.py` |

Also: `application/pending_reconciliation.py` — shares one `UnitOfWork` transaction for final local resolution (receipt save + idempotency resolution) after broker evidence is fetched outside the transaction.
