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

## Opening the evidence

Use `SqliteDatabase.open_existing` for offline or quiesced inspection. It opens
only an existing file, requires the exact current schema, never creates or
migrates anything, and rejects write transactions. A missing path raises
`FileNotFoundError`; it is never reported as an empty worklist.

```python
from quantx.application.quarantine_worklist import (
    QuarantineWorklistReadService,
    render_quarantine_worklist_item,
)
from quantx.persistence.sqlite import SqliteDatabase, SqliteSubmissionQuarantineRepository

with SqliteDatabase.open_existing("quantx.db") as database:
    service = QuarantineWorklistReadService(
        quarantine=SqliteSubmissionQuarantineRepository(database),
    )
    cursor = None
    while True:
        worklist = service.read(limit=100, cursor=cursor)
        if not worklist.available:
            raise RuntimeError(f"quarantine evidence unavailable: {worklist.error}")
        for item in worklist.items:
            print(render_quarantine_worklist_item(item))
        if worklist.next_cursor is None:
            break
        cursor = worklist.next_cursor
```

If the application already owns the database in this process, pass its existing
`SqliteDatabase` and repository to the service. Do not open a second long-lived
connection against a live host as an operational pattern; the adapter documents
single-process ownership, and `open_existing` is intended for a quiesced host or
a stable offline copy.

## Paging and bounds

`limit` defaults to 100 and is bounded to 1–1000. When more readable evidence
exists, `truncated` is true and `next_cursor` is an opaque continuation value.
Pass that value back unchanged; `truncated` is true exactly when `next_cursor` is
not `None`. Invalid limits and cursors fail before any store access.

A page is ordered by `observed_at`, then observation id. Cursors carry that same
ordering key, so pages are deterministic and never overlap. Ordering is not
based on rowid or an offset, and evidence inserted between reads does not cause
an already returned item to move into a later page.

The SQLite adapter bounds each read to 10,000 rows and 4,096 payload characters
per row by default. Exceeding either bound returns `UNAVAILABLE`; it is never
presented as `truncated`, an empty worklist, or a partial page. Those defaults
can be raised explicitly on `SqliteSubmissionQuarantineRepository`, but a
backlog beyond the configured row bound requires a separately reviewed indexed
pagination/schema change. Until then it is reported as unreadable rather than
silently omitted.

## Result semantics

| Field | Meaning |
|---|---|
| `status = OK` | The store was read. `items` is the (possibly empty) evidence page. |
| `status = UNAVAILABLE` | The store, a stored record, or the bounded read could not be completed. Nothing can be concluded; `error` is a bounded reason and, for a corrupt record, a bounded display-safe observation id. |
| `items = ()` with `OK` | Successful read; no evidence remains in this page (and, without a cursor, none in the readable snapshot). |
| `available` | `True` only for a successful read. |
| `requires_operator_reconciliation` | `True` when items exist **or** the read was `UNAVAILABLE`. Unknown evidence is never presented as a clear queue. |
| `truncated` | Only meaningful for `OK`: more readable evidence exists beyond this page. |
| `next_cursor` | Only meaningful for `OK` with `truncated = True`: opaque continuation for the next page. |

Reads are idempotent and leave evidence, reservations, receipts, idempotency
completion, and trading-gate state untouched. A read failure never degrades to
an empty worklist.

## Item fields and display safety

Each item carries one quarantine record and the state `UNRESOLVED`. Available
fields are the ones the write path bounded: `observation_id`, `kind`
(`TRANSPORT_UNCERTAIN`, `BROKER_UNKNOWN`, `IDENTITY_REJECTED`,
`MALFORMED_RECEIPT`, `RECEIPT_PERSISTENCE_UNCERTAIN`), `client_order_id`,
`request_correlation_id`, `source`, `broker_order_id`, `outcome`,
`order_status`, `observed_at`, and a bounded `reason`. Missing metadata is
`None`; it is never fabricated. Raw broker payloads, tokens, credentials, and
unbounded exception text are not stored and therefore cannot be shown.

Serialized payloads always include the optional keys, even when their value is
`null`. A stored payload that omits an optional key, or whose stored identity
columns disagree with the payload identity, is structurally malformed and fails
closed as `UNAVAILABLE`.

Some bounded broker-derived text can still contain newlines or terminal control
characters. Persisted evidence is preserved unchanged, but operator-facing text
must be rendered through `render_quarantine_worklist_item`. It shows C0/C1
controls, ANSI escape bytes, NUL, CR, LF, tab, and Unicode line/paragraph
separators as printable escape sequences, and bounds the rendered item. Do not
print the underlying fields directly.

`UNRESOLVED` describes the immutable quarantine record, which has no resolution
column. It is not a live status of the reservation. An operator must cross-check
the authoritative idempotency/reconciliation contracts before concluding that
work remains or that an outcome is known.

## What an operator does with a finding

1. Preserve the evidence; do not delete or rewrite quarantine rows.
2. Treat the case as requiring investigation. Do not infer a broker rejection,
   cancellation, or fill from the presence or absence of an item.
3. Reconcile only with separately authorized broker evidence through the
   existing reconciliation contracts (`reconcile_pending_execution`) or the
   audited operator closure (`resolve_pending_operator`) — never by editing
   quarantine rows or resubmitting an uncertain order.
4. If evidence is absent where a reservation is still pending, corrupt,
   contradictory, or beyond the readable bound, stop and escalate with the
   observation and client-order ids.

## Known gap (not approved process)

There is no approved, documented operator escalation path or runbook for
stranded PENDING reservations beyond the programmatic contracts above. This
worklist makes the evidence visible but deliberately does not invent an
approval, acknowledgement, or automated recovery workflow. A bounded operator
runbook/CLI is a separate follow-up decision.
