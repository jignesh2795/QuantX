# ADR 0061: Durable Account/Connection Pending Scope — C2d

**Status:** Implementation candidate committed; exact-SHA validation pending. No LIVE-readiness claim.
**Base:** `46c5241b85486f344a1f285bb19a20d9e0bb7cf6`
**Implementation branch:** `feat/slice-c2d-durable-pending-scope-v1`
**Code candidate:** `7f5deca27c0c5dc00af9c7a339ffc4993a33e594`
**Validation:** Pending exact-SHA local tests, Ruff formatting/lint, strict mypy, and diff checks. This ADR claims no test result.

## Context

ADR 0057 defines two separate remaining admission controls: C2d must supply durable account/connection-scoped lookup for unresolved submissions, while C2e must provide durable exclusive concurrent admission/lease semantics. An unknown submission is not safe to retry merely because a new request has a different client-order identifier. Missing or corrupt scope data must therefore fail closed rather than be silently skipped.

## Decision

### Durable normalized scope

SQLite schema v10 adds `pending_execution_scopes`, keyed by `client_order_id` and associated with the canonical `idempotency_reservations` row. It stores the reservation fingerprint, a constrained `KNOWN` or `UNKNOWN` status, optional account and broker-connection identifiers, and creation instant. Indexed lookup uses `idx_pending_execution_scopes_by_scope`; unresolved-reservation discovery is supported by `idx_idempotency_reservations_pending`.

When a new idempotency reservation is inserted, its normalized scope row is inserted in the same SQLite transaction. The store records `KNOWN` only when a typed pending context identifies a LIVE execution with canonical account and broker-connection IDs. It never guesses a missing connection or derives a financial/trading scope from display labels. Reservations without sufficient canonical scope are stored as `UNKNOWN`.

Migrations from schema versions 1–8 create the new table and indexes during upgrade. Version 9 has an explicit migration to version 10. Migrations deliberately do not derive or backfill scope for legacy reservations: an unresolved old reservation without a normalized scope row is treated as globally unknown. This avoids interpreting historical serialized data as newly authoritative scope.

### Guard semantics

`SqlitePendingScopeGuard.check(account_id, connection_id, checked_at=...)` uses one read transaction and the indexed scope. The result is:

- `PENDING` when an unresolved reservation is validly bound to that exact account/connection pair;
- `CLEAR` when no unresolved row for that pair exists and all remaining unresolved records have valid normalized scope;
- `UNKNOWN` globally if any unresolved reservation lacks scope, has `UNKNOWN` status, has malformed scope, or has a stored fingerprint that differs from its reservation; or if orphaned scope/quarantine evidence exists or SQLite read fails.

A reservation is unresolved when it has no canonical receipt and no durable operator or definite-not-submitted resolution. Completed or explicitly resolved reservations do not block. A quarantine record with no corresponding reservation makes the global query `UNKNOWN`. The guard does not use broker I/O.

### Runtime enforcement

`ExecutionOrchestrator` accepts an injected `PendingScopeGuard`. On LIVE submission, the guard is checked inside the in-process trading-gate admission section and before creating a new pending reservation. The observation must be a canonical `PendingScopeResult` for the exact account/connection pair and the exact check instant. Missing guard, an exception, malformed or mismatched result, `PENDING`, and `UNKNOWN` all return `BLOCKED` before reservation and broker submission. Only `CLEAR` permits the existing reservation flow to continue.

This is deliberately not represented as C2e. The check alone does not create a cross-process exclusive lease and does not close the race between independent processes. C2e remains required for durable concurrent admission, lease expiry, crash recovery, and safe release semantics.

## Migration and verification requirements

Validation must prove:

1. Fresh schema and versions 1–9 migrate to schema v10 with the pending-scope table and indexes.
2. New canonical LIVE reservations persist account/connection scope atomically with the idempotency reservation.
3. Legacy/missing/unknown/malformed or fingerprint-mismatched scopes return global `UNKNOWN`, including after restart.
4. A matching pair returns `PENDING`; another account or connection does not match a well-formed scoped reservation.
5. Completion and explicit durable resolutions stop blocking; unreadable database and orphaned quarantine evidence fail closed.
6. The runtime guard is mandatory for LIVE submission and missing, failing, mismatched, stale-time, PENDING, or UNKNOWN outcomes leave the reservation store and broker submit untouched.
7. Focused tests, the full suite, Ruff format/lint, strict mypy, and diff checks pass at one exact SHA.

## Relationship to LIVE readiness

C2a daily realized P&L, C2b whole-account position evidence, and C2c Dhan financial-state/margin authority remain **BLOCKED**. C2e is still necessary, and end-to-end binding of the risk approval to the request fingerprint and evidence identity/time is still unresolved. `build_live_execution` continues to refuse production LIVE composition. No credentials, broker I/O, orders, or LIVE trading were used.
