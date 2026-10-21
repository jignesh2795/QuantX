# Quarantine Evidence Worklist (bounded read-only)

**Status:** implemented bounded read-only inspection view over durable
quarantined submission evidence.

The P0.3 remediation records uncertain, malformed, or identity-rejected
submission observations in a durable, strictly non-authoritative quarantine
store. This worklist is the first consumer of that evidence: it tells an
operator **what evidence exists in the bounded readable snapshot for manual
reconciliation**. It is not a complete-inventory guarantee; a backlog above the
row bound is reported as `UNAVAILABLE` and requires the escalation procedure
below. It does not reconcile anything.

## What it is not

- Not authoritative trading state. Quarantined observations never complete
  idempotency, never become canonical receipts, and never affect positions or
  accounting — and reading them changes none of that.
- Not a resolution tool. There is no acknowledge, resolve, retry, cancel, or
  "mark handled" operation here, and no gate/admission change.
- Not broker evidence. It performs no broker, exchange, transport, or network
  access; it reads local SQLite rows only.
- Not complete inventory or live monitoring. It returns one bounded page from
  one snapshot per call. A backlog above 10,000 readable rows, or a source that
  changes during a pass, is outside the supported contract (see below).
- Not proof of a broker outcome. An item records that local outcome knowledge
  was incomplete when the observation was written. It does not prove the
  underlying reservation is still pending, and it does not prove the broker
  rejected, cancelled, or filled anything.

## Bounded-view contract

- The adapter materializes at most 10,000 readable rows per call. More than
  10,000 readable rows returns `UNAVAILABLE` before any page is produced; it is
  never presented as `truncated`, an empty worklist, or a partial inventory.
- Pagination exists to bound operator-visible output, not to page through an
  arbitrarily large table. Every page re-reads the bounded store, so a full
  pass costs `ceil(rows / limit)` store reads.
- Each page reads a separate snapshot. A pass therefore requires a quiesced or
  offline source; after any source mutation (including deletions), restart the
  pass from the initial cursor. See "Paging, cursors, and cost".
- If routine complete inventory or live monitoring is a real requirement, stop:
  that needs a separately designed and reviewed indexed pagination/schema
  change. This change intentionally adds no migration or production index, and
  documentation alone does not provide that guarantee.

### Above the row bound: escalation and retrieval

At more than 10,000 readable rows the service returns `UNAVAILABLE`. That is
not a queue status; it means the bounded view cannot answer the question. The
operator must not interpret it as "nothing to reconcile" and must not delete or
rewrite rows to fit the bound. Use the following separately authorized offline
retrieval instead:

1. Stop the writer and preserve the original store unopened.
2. Take a disposable copy after the last writer closed, including any
   `-wal`/`-shm` companions, and record the copy path, byte size, SHA-256
   digest, and `schema_version` before opening it.
3. Perform retrieval through a separately reviewed, one-off offline export
   script (never through the production service): open the copy read-only
   (`mode=ro`), stream rows ordered by `(observed_at, observation_id)` in
   bounded batches, decode every payload with
   `QuarantinedSubmissionObservation.from_payload`, and fail closed on the first
   decode error instead of skipping it.
4. Write the exported evidence to a separate artifact; do not modify the copy.
5. Reconcile only through the existing authorized contracts (see "What an
   operator does with a finding") and record the export used as evidence.

A reviewed temporary raise of `max_scan_rows` on
`SqliteSubmissionQuarantineRepository` is acceptable inside such an offline
export process, but it is not a supported production default and does not
create a complete-inventory guarantee. A routine need for complete inventory
still requires the indexed pagination/schema design and review.

## Opening the evidence

Use `SqliteDatabase.open_existing` for offline or quiesced inspection. It opens
only an existing file, requires the current schema version, never creates or
migrates anything, and rejects write transactions. Missing or unreadable tables
are not repaired; the read fails closed until the database is repaired. A
missing path raises `FileNotFoundError`; it is never reported as an empty
worklist.

The connection is SQLite-enforced read-only (`mode=ro`), not merely
`PRAGMA query_only`: the engine refuses `INSERT`, `UPDATE`, `DELETE`, and DDL
even after `query_only` is turned off through the public connection handle.
`query_only` and the write-transaction guard remain as defense in depth.
Database creation and ordinary production write/transaction behavior are
unchanged; only `open_existing` is affected.

Read-only is **not** side-effect free. A read-only connection cannot checkpoint,
so a hot WAL is read where it stands and the main database file is not rewritten
by a read. SQLite's WAL machinery can still create or update `-wal`/`-shm`
companion files: an empty `-wal` may appear for a cleanly closed database, and
SQLite rebuilds the `-shm` wal-index when a hot copy is read without one in a
writable directory. This is therefore not byte-preserving inspection of a
directory: preserve the only copy of evidence unopened, and inspect a disposable
copy taken after the last writer closed.

Before opening, record the intended copy's absolute path, size, and SHA-256.
After opening, compare `database.path` with the intended path; `open_existing`
already rejects a missing file, a foreign schema, or an incompatible schema
version. Only after that verification may an `OK` result with no items be read
as "this selected store contains no readable worklist items". A store that is
the wrong copy, or one that was replaced after the digest was taken, is not a
clear worklist.

```python
import hashlib
from pathlib import Path

from quantx.application.quarantine_worklist import (
    QuarantineWorklistReadService,
    render_quarantine_worklist_item,
)
from quantx.persistence.sqlite import SqliteDatabase, SqliteSubmissionQuarantineRepository

evidence_copy = Path("evidence-copy.db").absolute()
digest_before = hashlib.sha256(evidence_copy.read_bytes()).hexdigest()

with SqliteDatabase.open_existing(evidence_copy) as database:
    # Verify the selected store before interpreting any result, especially an
    # OK result with no items.
    assert database.path == str(evidence_copy)
    assert hashlib.sha256(evidence_copy.read_bytes()).hexdigest() == digest_before

    service = QuarantineWorklistReadService(
        quarantine=SqliteSubmissionQuarantineRepository(database),
    )
    cursor = None
    while True:
        worklist = service.read(limit=1000, cursor=cursor)
        if not worklist.available:
            raise RuntimeError(f"quarantine evidence unavailable: {worklist.error}")
        for item in worklist.items:
            print(render_quarantine_worklist_item(item))
        if worklist.next_cursor is None:
            break
        cursor = worklist.next_cursor
```

The source must be quiesced or offline for the duration of the pass. If the
application already owns the database in this process, pass its existing
`SqliteDatabase` and repository to the service. Do not open a second long-lived
connection against a live host as an operational pattern; the adapter documents
single-process ownership, and `open_existing` is intended for a quiesced host or
a stable offline copy.

## Paging, cursors, and cost

`limit` defaults to 100 and is bounded to 1–1000. When more readable evidence
exists, `truncated` is true and `next_cursor` is an opaque continuation value.
Pass that value back unchanged; `truncated` is true exactly when `next_cursor` is
not `None`. Malformed limits and cursors fail before any store access.

A page is ordered by `observed_at`, then observation id. Cursors carry that same
ordering key, so pages are deterministic and never overlap within one unchanged
snapshot. Ordering is not based on rowid or an offset.

Cursor lifetime is **one inspection pass against one unchanged store**. A cursor
is not persisted, not durable, and not bound to a database identity. Reusing a
cursor against another database, another run, or a mutated store can silently
produce a partial view, so the service rejects a well-formed cursor whose
ordering anchor is absent from the readable evidence (`ValueError`, not
`UNAVAILABLE`). Reuse the cursor only with the same unchanged store; restart
from `None` after any source mutation.

Each page read is a bounded snapshot, but a multi-page pass is not one snapshot
across pages: every page re-reads and decodes the entire readable set. Evidence
inserted between page reads, especially with an ordering key earlier than the
cursor, can be absent from that pass. A cursor whose anchor still exists but
whose following rows were removed returns `OK` with an empty page: that is a
real empty tail, not a lost page.

### Measured cost

Measured on the development workstation (Windows 11 22H2, CPython 3.12.12,
warm cache, local SSD) against a real read-only copy with 5,000 rows and
payloads of roughly 750 characters:

| Read | Median | Notes |
|---|---|---|
| `read(limit=100)` | ~1.05 s | one page; decodes the full readable set |
| `read(limit=1000)` | ~1.4 s | one page; same store work, more items built |
| Full pass, `limit=100` | ~59 s | 50 pages, each re-reading 5,000 rows |
| Full pass, `limit=1000` | ~6.1 s | 5 pages, each re-reading 5,000 rows |
| One `list_all()` | ~1.1 s | dominated by per-row JSON decode |

These numbers are host-specific and grow linearly with the number of readable
rows per page; at the 10,000-row ceiling the per-page cost is roughly double.
Use the default page size for interactive terminal display, and `limit=1000`
for offline inspection passes: it reduced the measured pass time by about 10x
in this environment. A faster or larger-than-page-size listing would require the
separately reviewed indexed pagination design.

## Payload-size contract (writer = reader)

One canonical constant, `MAX_SERIALIZED_PAYLOAD_CHARS` in
`quantx.execution.receipts.quarantine`, is shared by the SQLite write boundary
and the default read bound. It is derived from the field validation rules and
the serialization settings actually used, not chosen arbitrarily:

- `json.dumps(..., sort_keys=True, separators=(",", ":"))` with the stdlib
  `ensure_ascii=True` default. A quote or backslash costs 2 characters, a BMP
  or control code point costs 6 (`\uXXXX`), and an astral code point is
  serialized as a surrogate pair costing 12.
- Six bounded text fields (`client_order_id` and the five optional text fields)
  of at most 256 code points: `6 × (256 × 12 + 2) = 18,444`.
- `reason` of at most 512 code points: `512 × 12 + 2 = 6,146`.
- `kind`: longest enum value (29) plus quotes: `31`.
- `observation_id`: UUID text (36) plus quotes: `38`.
- `observed_at`: widest legal `isoformat()` result
  (`9999-12-31T23:59:59.999999+23:59:59.999999`, 42) plus quotes: `44`.
- JSON envelope: 2 braces, the `"key":` prefix of 10 sorted keys, and 9 commas:
  `153`.

Total: **24,856 characters**. The regression suite constructs an observation
that touches every one of those limits and asserts the serialized payload is
exactly this long, so the bound is proved tight rather than guessed.

Consequences:

- Every observation produced by the validated constructor serializes within the
  bound and is readable by the default reader. The write boundary still rejects
  an over-bound serialization before the insert (only a value whose runtime type
  lies about its serialized form can trigger it); it never stores a row the
  default reader would refuse, and the caller treats that rejection as a
  persistence failure and latches the existing fail-closed safety fault.
- A genuinely over-bound stored payload is reported as `UNAVAILABLE` with
  "payload exceeds the 24856-character bound"; it is never truncated, skipped,
  or rendered as a partial worklist.
- Lowering `max_payload_chars` below the write bound is an intentional
  fail-closed inspection option: it reports the store as unreadable above that
  bound instead of admitting an over-bound row. The default read bound equals
  the write bound.

## Result semantics

| Field | Meaning |
|---|---|
| `status = OK` | The store was read. `items` is the (possibly empty) evidence page. |
| `status = UNAVAILABLE` | The store, a stored record, or the bounded read could not be completed. Nothing can be concluded; `error` is a bounded, display-safe reason (a corrupt record also carries a bounded display-safe observation id; a driver failure carries a static description, never the raw driver message). |
| `items = ()` with `OK` | Successful read; no evidence remains in this page. Without a cursor this means the readable snapshot is empty — but only after verifying the selected store, and never as a claim about rows beyond the 10,000-row bound. |
| `available` | `True` only for a successful read. |
| `requires_operator_reconciliation` | `True` when items exist **or** the read was `UNAVAILABLE`. Unknown evidence is never presented as a clear queue. |
| `truncated` | Only meaningful for `OK`: more readable evidence exists beyond this page. |
| `next_cursor` | Only meaningful for `OK` with `truncated = True`: opaque single-pass continuation for the next page. |

Reads are idempotent and leave evidence, reservations, receipts, idempotency
completion, and trading-gate state untouched. A read failure never degrades to
an empty worklist.

## Item fields, persisted-payload strictness, and display safety

Each item carries one quarantine record and the state `UNRESOLVED`. Available
fields are the ones the write path bounded: `observation_id`, `kind`
(`TRANSPORT_UNCERTAIN`, `BROKER_UNKNOWN`, `IDENTITY_REJECTED`,
`MALFORMED_RECEIPT`, `RECEIPT_PERSISTENCE_UNCERTAIN`), `client_order_id`,
`request_correlation_id`, `source`, `broker_order_id`, `outcome`,
`order_status`, `observed_at`, and a bounded `reason`. Raw broker payloads,
tokens, credentials, and unbounded exception text are not stored and therefore
cannot be shown.

Two different contracts apply to optional text:

- **Before persistence**, malformed broker-derived values are sanitized to
  `None` by `from_receipt`; an observation must stay recordable. A wrong-typed,
  empty, or overlong broker value is never fabricated into evidence.
- **When reading persisted evidence**, only the exact shape the writer produces
  is accepted. A stored payload with a wrong-typed, empty, non-stripped, or
  overlong optional value, a missing key, or an identity column that disagrees
  with the payload is treated as **corruption** and returns `UNAVAILABLE`; it is
  not silently normalized into apparently valid evidence. Unknown extra keys are
  ignored and never surfaced, so a hand-edited row cannot inject display text.

Some bounded broker-derived text can still contain newlines, terminal control
characters, bidi formatting controls, or lone surrogates. Persisted evidence is
preserved unchanged, but operator-facing text must be rendered through
`render_quarantine_worklist_item` (or the shared `neutralize_display_text`). The
tested renderer:

- escapes CR, LF, tab, NUL, all other C0/C1 controls, and ANSI escape bytes;
- escapes Unicode line/paragraph separators (U+2028, U+2029);
- escapes bidirectional formatting/isolate controls (U+061C, U+200E, U+200F,
  U+202A–U+202E, U+2066–U+2069, including U+202E and U+2066);
- escapes lone surrogates so terminal encoding cannot fail;
- keeps printable Unicode unchanged and bounds the rendered item.

Do not print the underlying observation fields directly. The renderer
neutralizes these categories for terminal output; it does not sanitize the
persisted bytes and is not a general HTML/SQL/log-injection sanitizer.

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
   observation and client-order ids, the evidence-copy path, size, SHA-256, and
   `schema_version`.

## Deliberately deferred

- Complete inventory, live monitoring, and cursor durability across runs would
  need a schema/index design (for example a durable cursor identity or indexed
  keyset pagination) and a separate review. No migration or production index is
  introduced here.
- A supported CLI/runbook for the above-bound retrieval remains a separate
  decision; the escalation procedure above is manual and review-gated.
- The worklist read port (`QuarantineEvidenceReader`) is deliberately separate
  from the execution-side `SubmissionQuarantineRepository` so future adapters
  are not forced to implement `list_all`.

## Known gap (not approved process)

There is no approved, documented operator runbook for *resolving* stranded
PENDING reservations beyond the programmatic contracts above; the retrieval
procedure in this document covers listing evidence only. This worklist makes the
evidence visible but deliberately does not invent an approval, acknowledgement,
or automated recovery workflow. A bounded operator runbook/CLI is a separate
follow-up decision.
