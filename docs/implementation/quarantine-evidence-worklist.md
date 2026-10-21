# Quarantine Evidence Worklist (read-only)

**Status:** implemented read-only consumer of durable quarantined submission evidence.

The P0.3 remediation records uncertain, malformed, or identity-rejected
submission observations in a durable, strictly non-authoritative quarantine
store. This worklist is the first consumer of that evidence: it tells an
operator **what evidence exists for manual reconciliation**. It does not
reconcile anything.

## What it is not

- Not authoritative trading state. Quarantined observations never complete
  idempotency, never become canonical receipts, and never affect positions or
  accounting — and reading them changes none of that.
- Not a resolution tool. There is no acknowledge, resolve, retry, cancel, or
  "mark handled" operation here, and no gate/admission change.
- Not broker evidence. It performs no broker, exchange, transport, or network
  access; it reads local SQLite rows only.
- Not proof of a broker outcome. An item records that local outcome knowledge
  was incomplete when the observation was written. It does not prove the
  underlying reservation is still pending, and it does not prove the broker
  rejected, cancelled, or filled anything.

## Invocation

There is no CLI (the CLI remains deferred under ADR-008). Invoke the read
service as a programmatic local API:

```python
from quantx.application.quarantine_worklist import QuarantineWorklistReadService
from quantx.persistence.sqlite import SqliteDatabase, SqliteSubmissionQuarantineRepository

database = SqliteDatabase("quantx.db")
try:
    worklist = QuarantineWorklistReadService(
        quarantine=SqliteSubmissionQuarantineRepository(database),
    ).read(limit=100)
finally:
    database.close()

if not worklist.available:
    raise RuntimeError(f"quarantine evidence unavailable: {worklist.error}")
for item in worklist.items:
    observation = item.observation
    print(
        item.state.value,
        observation.kind.value,
        observation.client_order_id,
        observation.request_correlation_id,
        observation.broker_order_id,
        observation.observed_at.isoformat(),
        observation.reason,
    )
```

`limit` defaults to 100 and is bounded to 1–1000; `truncated` reports whether
more evidence exists beyond the returned page. There is no additional filter:
every durable quarantine row is unresolved evidence, and filtering by a
cross-referenced resolution state would risk presenting a stale or incomplete
join as authoritative.

## Result semantics

| Field | Meaning |
|---|---|
| `status = OK` | The store was read. `items` is the (possibly empty) evidence list. |
| `status = UNAVAILABLE` | The store or a stored record could not be read. Nothing can be concluded; `error` names the failure and, for a corrupt record, a bounded form of its observation id. |
| `items = ()` with `OK` | Successful read, no quarantine evidence. This is the only "nothing in this store" signal. |
| `available` | `True` only for a successful read. |
| `requires_operator_reconciliation` | `True` when items exist **or** the read was `UNAVAILABLE`. Unknown evidence is never presented as a clear queue. |
| `truncated` | Only meaningful for `OK`: more durable observations exist beyond `limit`. |

Ordering is deterministic: observation time, then observation identity. Reads
are idempotent and leave evidence, reservations, receipts, idempotency
completion, and trading-gate state untouched. A read failure never degrades
to an empty worklist.

## Item fields

Each item carries one sanitized quarantine record and the state
`UNRESOLVED`. Available fields are the ones the write path already sanitized
and bounded: `observation_id`, `kind` (`TRANSPORT_UNCERTAIN`,
`BROKER_UNKNOWN`, `IDENTITY_REJECTED`, `MALFORMED_RECEIPT`,
`RECEIPT_PERSISTENCE_UNCERTAIN`), `client_order_id`, `request_correlation_id`,
`source`, `broker_order_id`, `outcome`, `order_status`, `observed_at`, and a
bounded `reason`. Missing optional identity is `None`; it is never fabricated.
Raw broker payloads, tokens, credentials, and unbounded exception text are not
stored and therefore cannot be shown.

`UNRESOLVED` describes the immutable quarantine record, which has no
resolution column. It is not a live status of the reservation. An operator
must cross-check the authoritative idempotency/reconciliation contracts before
concluding that work remains or that an outcome is known.

## What an operator does with a finding

1. Preserve the evidence; do not delete or rewrite quarantine rows.
2. Treat the case as requiring investigation. Do not infer a broker rejection,
   cancellation, or fill from the presence or absence of an item.
3. Reconcile only with separately authorized broker evidence through the
   existing reconciliation contracts (`reconcile_pending_execution`) or the
   audited operator closure (`resolve_pending_operator`) — never by editing
   quarantine rows or resubmitting an uncertain order.
4. If evidence is absent where a reservation is still pending, corrupt, or
   contradictory, stop and escalate with the observation and client-order ids.

## Known gap (not approved process)

There is no approved, documented operator escalation path or runbook for
stranded PENDING reservations beyond the programmatic contracts above. This
worklist makes the evidence visible but deliberately does not invent an
approval, acknowledgement, or automated recovery workflow. A bounded operator
runbook/CLI is a separate follow-up decision.
