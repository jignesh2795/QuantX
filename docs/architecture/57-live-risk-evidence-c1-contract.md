# ADR 0057: LIVE Risk Evidence Authority and Fail-Closed Slice C1

**Status:** Contract implemented; sanctioned LIVE composition deliberately blocked pending authority/admission integration.
**Baseline:** `a34ec73b3f9457079882ca99b895a8efeae23d73`
**Implementation branch:** `feat/slice-c1-live-risk-evidence-core-v1`
**Validation:** Pending exact-SHA local validation. No test result is claimed by this ADR.

## Context

The current LIVE composition accepts a caller-provided `risk_inputs_for_request`
callable that can supply financial state, exposure, prices, margin, and realized
P&L. The trusted-clock work only protects the freshness calculation against a
fabricated evaluation-time claim; it does not establish that the observed
account values are authoritative.

The current Dhan adapter does not provide the full evidence contract needed for
sanctioned LIVE approval. In particular, its position surface is not proof of a
whole-account book, the account state has no authoritative realized daily P&L
field, and the current integration does not provide a canonical margin
authority or durable account-scoped risk-admission lease.

## Decisions

### 1. Realized daily P&L authority

Only a complete, whole-account source declared as
`BROKER_REPORTED` or `QUANTX_LEDGER_WITH_BROKER_TRADE_BOOK` is eligible.
Receipt-only P&L, operator-supplied P&L, incomplete daily coverage, mismatched
trading days, stale/future timestamps, currency mismatches, and uncaptured
activity are rejected. Missing evidence is not zero. The builder requires both the trusted trading
date and the session-start instant from the India session calendar to match the
P&L authority's declared trading day and day-start boundary.

No qualifying production authority is implemented at the baseline. This remains
a blocking prerequisite.

### 2. Whole-account position evidence

The position contract requires all three explicit surfaces: `POSITIONS`,
`HOLDINGS`, and `MARKS`. Every position must retain canonical instrument and
product identity, signed quantity, average price, mark price, mark timestamp,
currency, and mark provenance. The adapter must reconcile/aggregate vendor rows
under its explicit, auditable merge policy before creating the canonical book;
the core rejects duplicate instrument/product keys rather than silently summing.

An empty open-position list is not proof of an empty account. Missing holdings,
incomplete surfaces, unmapped instruments, stale marks, or currency mismatch
reject the evidence.

### 3. Margin authority

The new evidence builder consumes the authoritative `MarginEvidence` values.
It rejects request-declared margin that differs from the authority. The legacy
risk path still contains a duplicated snapshot-margin field for compatibility;
it is not considered an authority contract. No broker margin authority or
canonical Dhan conversion is implemented.

### 4. Currency and unsupported limits

The evidence builder requires one explicit base currency and validates it
against every account, P&L, margin, instrument, position, and reference-price
component. FX conversion is out of scope.

`max_unrealized_loss` is a mandatory strictly positive Decimal for LIVE limits.
It measures total whole-book unrealized loss at the evidence cut:
`max(0, -sum((mark - average_price) * signed_quantity * multiplier))`.
Realized and unrealized limits are independent. A profitable realized day does
not offset unrealized loss. The limit comparison is strict `>`; an exact-limit
value passes, and no durable breach latch is added here.

LIVE composition rejects until authorities and admission controls are fully
integrated. Future sanctioned LIVE policy must also reject `max_drawdown` until
equity/high-water-mark authority exists, and reject
`max_instrument_concentration` until gross-basis semantics exist.

### 5. Pending submissions and concurrent admission

The application module defines fail-closed pending-scope and concurrency
admission contracts. A pending `UNKNOWN` is not clear. These interfaces alone
do not implement a durable SQLite scope query or a lease lifecycle.

C2d must implement indexed, durable account/connection pending-scope lookup,
with malformed scope blocking globally. C2e must implement durable exclusive
admission/lease semantics with expiry and recovery rules. The current
`ExecutionOrchestrator` has not been wired to hold/release that admission over
the critical submit-admission path. Therefore no production LIVE stack is
returned by `build_live_execution` in this C1 cutover.

### 6. Runtime composition

The `risk_inputs_for_request` configuration field has been removed, so the
sanctioned composition contract no longer accepts a caller-controlled risk
input provider. `build_live_execution` raises a fixed
`LiveExecutionCompositionError` before mutating durable gate state.

This is intentionally stricter than refusing Dhan alone: until the typed
evidence builder, exact registered-adapter binding, pending guard, concurrency
lease, and risk-approval binding are integrated end-to-end, every sanctioned
LIVE composition stays unavailable.

## Implementation scope

This branch adds:
- typed domain evidence records for P&L, whole-account positions, required
  surfaces, margin, and reference prices;
- deterministic evidence validation and a builder that derives canonical
  `TradeIntent`, `RiskContext`, and `RiskSnapshot` inputs from those records;
- mandatory `max_unrealized_loss` validation and deterministic risk-engine
  enforcement;
- synthetic-fixture unit tests for the new evidence contract;
- removal of the caller-controlled risk-input provider from LIVE composition
  and a fail-closed cutover that refuses to construct a sanctioned LIVE stack.

The implementation is not yet a complete LIVE authority path. An optional
`RiskApprovalBinding` now identifies the exact request fingerprint, evidence
identity/cut, currency, account/connection, trading day, and evaluation instant;
the evidence-backed evaluator helper creates and validates that binding.
However, this binding is not yet enforced end-to-end by
`ApprovedExecutionRequest` and `ExecutionOrchestrator`, and the new builder is
not wired into a returned execution stack. These remain blockers, not implied
capabilities.

## Execution-safety test coverage retained by the fail-closed cutover

The former factory-success tests cannot keep their old expected outcomes because
`build_live_execution` now intentionally raises until the missing LIVE evidence
authorities and durable admission controls exist. The factory-specific tests are
therefore replaced with assertions that construction refuses without mutating
durable gate state, that the caller-controlled risk-provider field is absent,
and that market-policy derivation rejects non-India placements.

Existing lower-level regression coverage remains in the unchanged test modules:
- `tests/unit/application/test_execution.py` covers exactly-once/idempotent
  submission, gate blocking, malformed risk-evaluator results, and pre-submit
  fail-closed behavior.
- `tests/unit/application/test_live_risk.py` covers risk rejection before gate
  reservation/submission, failing evaluator refusal, trusted-clock authority,
  claim tolerance, and stale/future snapshot handling.

This is a source-level mapping only; it does not replace the required local
execution of the test suite at the final candidate SHA.

## Required follow-up before any LIVE stack can be constructed

1. C2a: **BLOCKED** for Dhan. The verified Dhan v2 positions, trade-history,
   and ledger contracts cannot establish complete whole-account realized daily
   P&L with defined daily charges; see
   `58-dhan-realized-daily-pnl-c2a-blocker.md`.
2. C2b: **BLOCKED for Dhan** until product/overlap semantics and authorized,
   timestamped marks can establish a complete whole-account book; see
   `59-dhan-whole-account-position-c2b-blocker.md`.
3. C2c: bind persisted account currency, convert authoritative account
   financial state, and implement margin authority.
4. C2d: implement durable scope-filtered pending lookup and fail-closed runtime
   guard.
5. C2e: implement durable concurrent admission/lease and integrate it into
   execution admission/release semantics.
6. Bind the exact request fingerprint and evidence identity/time to the live
   risk approval, and validate the binding before reservation/submission.
7. Wire the typed evidence source to the exact registered adapter used by
   `ExecutionOrchestrator.execute()`; validate the full control path and test
   that all refusals leave reservation and submission untouched.
8. Run exact-SHA local tests, formatting, Ruff, strict mypy, and diff checks.

## Safety non-claims

- No sanctioned LIVE stack is available from the composition factory in this
  branch.
- No Dhan broker evidence has been queried or verified by this implementation.
- No broker I/O, credentials, orders, or LIVE trading were used.
- No test command or test result is claimed here.
- Synthetic evidence used by unit tests is explicitly synthetic and cannot
  establish production authority.
