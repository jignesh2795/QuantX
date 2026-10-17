# Reconciliation (quantx-execution)

Pure comparison — no refresh, no retry, no readiness logic:

- `integrations/reconciliation/{account,orders,positions,broker_evidence}.py` — `AccountReconciler`, `OrderReconciler`, `PositionReconciler`, `BrokerOrderEvidence` (3 distinct lookup outcomes, never conflated).
- `application/reconciliation.py` — `OrderStateReconciliationWorkflow` (conservative aggregate; UNKNOWN stays UNKNOWN).
- `application/evidence_refresh.py` — `ReconciliationEvidenceRefresher` + `DefinitiveEvidencePolicy`.
- `application/not_found_policy.py`, `application/operator_resolution.py` — conservative NOT_FOUND / operator closure for unresolvable PENDING reservations.

Evidence rules (`docs/architecture/47-integration-boundaries.md`): integrations produce **observed evidence only**; missing evidence stays UNKNOWN; routing must never fail over across accounts (`account_id`, `connection_id`, `broker_id`, `market_context_id`).
