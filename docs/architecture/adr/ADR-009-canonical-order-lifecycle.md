# ADR-009: Canonical Order Lifecycle and Evidence Reduction

Status: Accepted for design; implementation is a separate, sequenced change (QX-03 / issue #192)

## Context

QuantX currently has three overlapping vocabularies with different coverage and different reduction behavior:

- `quantx.domain.enums.OrderStatus` is used by orders and execution receipts. It includes `CREATED`, `PENDING_SUBMIT`, `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `EXPIRED`, `FAILED`, and `UNKNOWN`.
- `quantx.execution.order_lifecycle.OrderLifecycleStatus` has a separate mutable transition table. It uses `SUBMITTED` and `ACKNOWLEDGED`, omits `PENDING_SUBMIT`, `EXPIRED`, and `FAILED`, and has different transition rules.
- `quantx.execution.receipts.models.ExecutionOutcome` overlaps status names but is carried by an individual execution receipt. Its meaning must not be assumed to be the aggregate order's current status.

The two lifecycle paths do not express identical guarantees. In particular, direct cancellation, cancellation while awaiting acknowledgement, partial-fill/remainder cancellation, expiry, and resolution from `UNKNOWN` need one defined policy. The P0 QX-01 receipt/request identity guard and QX-02 evidence-preserving receipt reduction are already merged; this decision builds on them and does not reopen their safety boundary.

Without one policy, adapters and application paths can disagree about whether an order is terminal, complete, uncertain, or eligible for continuation. An enum rename alone would not resolve this behavioral divergence.

## Decision

### 1. One canonical lifecycle vocabulary

Use `quantx.domain.enums.OrderStatus` as the canonical, broker-neutral order lifecycle vocabulary. Extend it with `SUBMITTED` so the state between durable dispatch intent and a confirmed broker acknowledgement is expressible. Keep `ACCEPTED` as the normalized acknowledged/open state; do not add `ACKNOWLEDGED` as a second synonym.

The target vocabulary and meanings are:

| Status | Meaning |
|---|---|
| `CREATED` | A normalized order exists but has not entered the durable dispatch workflow. |
| `PENDING_SUBMIT` | The order is approved and durably staged for dispatch; this alone is not evidence that the broker call occurred. |
| `SUBMITTED` | Evidence establishes that the broker/venue has received or is processing the order, but a stable accepted/open state has not yet been established. |
| `ACCEPTED` | Authoritative evidence establishes that the broker/venue accepted the order as live/open. |
| `PARTIALLY_FILLED` | Positive fill evidence exists and quantity remains unfilled. |
| `FILLED` | Fill evidence accounts for the entire requested quantity. A status string alone cannot manufacture missing fill quantity. |
| `CANCEL_PENDING` | A cancellation request is in progress; the order can still fill before cancellation is confirmed. |
| `CANCELLED` | Authoritative evidence confirms cancellation. A positive partial fill may coexist with this status. |
| `REJECTED` | Authoritative evidence confirms the order was rejected by the broker/venue. |
| `EXPIRED` | Authoritative evidence confirms the order expired. |
| `FAILED` | A definitive local failure is known to have occurred before a broker order could be live. Never use this for a timeout or uncertain post-submit result. |
| `UNKNOWN` | Available evidence cannot establish the order's state. Reconciliation is required; this is not a successful terminal state. |

`FAILED` is deliberately narrow. A broker rejection is `REJECTED`; an exception or timeout after a submit may have reached the broker is `UNKNOWN`, not `FAILED`. A failure to prove that an order exists is not, by itself, proof that it does not exist.

### 2. Keep lifecycle state, operation outcome, and evidence confidence distinct

- **Order lifecycle status** describes the best supported aggregate state of the order and its fills. `OrderStatus` owns this vocabulary.
- **Operation outcome** describes what a particular operation (submit, cancel, query, or reconcile) established. `ExecutionOutcome` remains receipt/operation metadata during migration; its values must be normalized explicitly and it must not be substituted for the aggregate order status. As consumers are migrated, retire status-shaped outcome values only through an explicit compatibility plan, not by silently changing persisted or public meanings.
- **Evidence provenance/confidence** records source, observation time, stable evidence identity, correlation, and whether evidence came from the authorized reconciliation path. It is metadata about why a state is believed, not a second order-status enum.

Broker-specific strings and SDK enums terminate at their adapter. The adapter maps them to canonical status plus preserved source/provenance; raw vendor strings do not become core states. Missing, stale, or conflicting evidence stays explicit.

### 3. One deterministic, evidence-preserving reducer

The receipt-based `ExecutionLifecycle` behavior is the migration anchor because it already tracks order quantity, aggregate fills, anomalies, reconciliation need, and continuation eligibility. The target is one canonical lifecycle reduction policy shared by receipt reconstruction and status/event observations—not two independently maintained transition tables.

Normalize incoming receipts and lifecycle observations into the same internal evidence representation, preserving at least: order identity, canonical status observation, event/observation time, stable evidence ID, source/provenance, fill evidence, and the operation/correlation identity where applicable. Keep immutable receipt records as the durable evidence; normalization must not replace or mutate them.

The canonical reducer must enforce these invariants:

1. Order identity and account/connection/correlation checks happen before evidence is treated as authoritative. Invalid or foreign evidence cannot complete idempotency or overwrite the canonical lifecycle.
2. Evidence is reduced deterministically using trustworthy observation/event time and a stable evidence identifier as a tie-breaker. Exact duplicate evidence is idempotent; one evidence ID with conflicting content is an error. Arrival order alone must not decide state.
3. Fill quantity comes from validated fill evidence, uses `Decimal`, is never negative, and never exceeds requested quantity. `FILLED` requires aggregate fill evidence equal to requested quantity. Overfill is rejected and contradictory evidence is surfaced.
4. A partial fill followed by confirmed cancellation remains `CANCELLED` with the evidenced fill and positive remainder; it is not eligible for automatic continuation.
5. `UNKNOWN` and any unresolved contradiction set `requires_reconciliation`, are not complete, and cannot continue. No ordinary status observation or optimistic local inference resolves `UNKNOWN`. A positively acknowledged, identity/correlation-validated cancel request may record `CANCEL_PENDING`, but it must retain `requires_reconciliation`; a cancel attempt, timeout, or uncertain cancel result leaves the lifecycle `UNKNOWN`.
6. Authoritative resolution is available only through the established reconciliation service after identity and evidence validation. Authority is conveyed by the trusted reconciliation boundary/result, not an arbitrary caller-controlled boolean. Resolution must be consistent with retained fill and terminal evidence.
7. A terminal status (`FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`, or `FAILED`) is absorbing for ordinary later status observations. Contradictory status or late-fill evidence is retained as an anomaly, forces reconciliation, and never silently rewrites the terminal status. `CANCEL_PENDING` and `UNKNOWN` are not terminal.
8. A cancellation request is an operation, not proof of cancellation. The state remains `CANCEL_PENDING` until confirmed; fills that race with cancellation are retained. A rejected cancel operation does not imply that the order itself was rejected.
9. No reduction or reconciliation path submits or resubmits an order. An unresolved post-submit outcome stays pending for reconciliation and cannot become permission for an automatic retry.

If timestamps, identities, quantities, or status observations conflict, deterministic ordering must not be used to hide the conflict. Preserve evidence and require the reconciliation policy to resolve it.

### 4. Transition policy

The transition policy distinguishes an ordinary lifecycle event from a validated observation of a state reached while intermediate events were not captured. Sparse broker polling must not be rejected merely because an intermediate notification was missed; however, skipping a state is allowed only when the observation itself is authoritative and consistent with retained evidence.

| Current state | Ordinary next states | Rules |
|---|---|---|
| `CREATED` | `PENDING_SUBMIT`, `FAILED` | `FAILED` only proves a definitive pre-submit local failure. A normalized authoritative broker observation may establish a later state if it is the first available evidence and passes consistency checks. |
| `PENDING_SUBMIT` | `SUBMITTED`, `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`, `UNKNOWN`, `FAILED` | A broker observation may skip intermediate states. `FAILED` requires proof the broker could not have a live order; ambiguity becomes `UNKNOWN`. |
| `SUBMITTED` | `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `EXPIRED`, `UNKNOWN` | Do not infer acceptance from a local submit return alone. Direct terminal observations require matching, authoritative evidence. |
| `ACCEPTED` | `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `EXPIRED`, `UNKNOWN` | A broker can reject an order after initial acknowledgement; map only explicit venue evidence. |
| `PARTIALLY_FILLED` | `PARTIALLY_FILLED`, `FILLED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `EXPIRED`, `UNKNOWN` | Partial fill is quantity-backed. A terminal remainder outcome retains all confirmed fills. |
| `CANCEL_PENDING` | `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`, `UNKNOWN` | A cancel rejection can leave the order live; a racing fill can complete it. Cancel requested is not cancel confirmed. |
| `UNKNOWN` | `CANCEL_PENDING` only on positively acknowledged, identity/correlation-validated cancel-in-progress evidence; otherwise no ordinary transition | This does not resolve the uncertainty: `requires_reconciliation` remains true, the order is not complete, and continuation is blocked. A cancel attempt, timeout, or uncertain cancel result leaves status `UNKNOWN`. A not-found response alone is not proof that resubmission is safe. |
| `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`, `FAILED` | No ordinary transition | Terminal state is preserved. Conflicts and late fills are added to evidence/anomalies and require reconciliation. |

Authoritative reconciliation may resolve `UNKNOWN` only to a state positively established by consistent, identity-checked evidence. It must never reset an order to `CREATED`. Returning to `PENDING_SUBMIT` is permitted only when durable dispatch evidence proves the broker submit call was never invoked; that resolution is not permission for an automatic retry. A not-found response or timeout alone cannot prove non-submission.\n\nThe table describes normal transitions, not an exhaustive list of every possible broker event. A status observation that skips a live intermediate state must still satisfy evidence, identity, quantity, and terminal-consistency rules. Any transition not listed and not covered by that explicit observation rule is rejected or treated as a reconciliation anomaly; it is never silently accepted.

### 5. Broker normalization and required golden flows

Dhan and other adapters map vendor statuses into the canonical vocabulary without widening the domain enum. The implementation must add table-driven adapter-to-lifecycle tests for Dhan's documented statuses:

| Dhan status | Canonical intent |
|---|---|
| `TRANSIT` | `SUBMITTED` |
| `PENDING` | `ACCEPTED` |
| `PART_TRADED` | `PARTIALLY_FILLED`, with validated fill quantity |
| `TRADED` | `FILLED`, only with full-quantity fill evidence |
| `REJECTED` | `REJECTED` |
| `CANCELLED` | `CANCELLED`, preserving any earlier partial fills |
| `EXPIRED` | `EXPIRED` |

These are normalized mappings to verify against the current adapter's documented semantics and fixtures before implementation is merged. If vendor documentation/fixtures show a different meaning, correct this table and the adapter tests together; do not coerce an unknown raw status into a plausible canonical state.

## Migration plan

1. **Contract tests first.** Encode the transition table, terminal absorption, quantity/evidence invariants, uncertainty rules, cancellation races, and Dhan golden sequences before changing the reducer.
2. **Inventory consumers.** Search all imports and call sites of `OrderStatus`, `OrderLifecycleStatus`, `ExecutionOutcome`, `OrderLifecycle`, `ExecutionLifecycle`, serialization, persistence, fixtures, and package exports. Separate direct status use from operation-outcome use.
3. **Normalize at the boundary.** Add the missing canonical `SUBMITTED` state and normalize event/receipt inputs into the canonical evidence form. Do not introduce a competing status enum or generic catch-all model module.
4. **Consolidate the reducer.** Route order lifecycle observations and receipt rebuilds through the canonical reducer. Retain the existing receipt-facing API or a narrow compatibility facade only while consumers migrate; it must delegate to the canonical policy rather than keep a second transition table.
5. **Compatibility deliberately.** Map legacy `ACKNOWLEDGED` to `ACCEPTED` only at a documented compatibility boundary. Treat `PENDING_SUBMIT` and `SUBMITTED` as different states. Keep `ExecutionOutcome` distinct; do not rename, remove, or reinterpret persisted/public values in this slice without an explicit migration plan.
6. **Remove obsolete policy after consumers migrate.** Delete the legacy state machine/enum only after usage inventory, compatibility coverage, serialization review, and boundary tests show there are no undocumented consumers.
7. **Validate the exact change.** Record base/head SHA; run focused lifecycle and adapter tests, the full suite, Ruff lint/format, strict mypy with the Dhan extra both present and absent, locked syncs, `git diff --check`, and a scope/import audit. GitHub Actions initialization failures are not test evidence while workflows fail before executable steps.

## Acceptance criteria for the implementation issue

- One canonical lifecycle status vocabulary and one canonical reduction policy are used by production consumers, with documented temporary shims only.
- Table-driven tests cover valid/invalid transitions, direct observations with missing intermediate events, terminal absorption, late fills, quantity conflicts, duplicate evidence, cancellation races, and authority-gated `UNKNOWN` resolution.
- Dhan golden sequences cover `TRANSIT`, `PENDING`, `PART_TRADED`, `TRADED`, `REJECTED`, `CANCELLED`, and `EXPIRED` from adapter mapping through lifecycle state.
- Partial-fill plus IOC/remainder cancellation is a resolved `CANCELLED` order when evidence is consistent; remaining quantity is not automatically resubmitted.
- Reconciliation is the only authority that resolves `UNKNOWN`; no adapter, timer, ordinary event, or ordinary submit/cancel response bypasses it.
- No broker submission behavior, persistence schema, LIVE capability, or auto-retry semantics are expanded.
- Exact-SHA test/static-analysis and diff-scope evidence is recorded; no production broker order is sent during validation.

## Consequences

### Positive

- Broker adapters, receipt reconstruction, and lifecycle consumers share one state vocabulary and evidence policy.
- Order state cannot be confused with the outcome of one operation or the confidence of one observation.
- Missing or contradictory evidence fails closed without erasing fills or enabling resubmission.
- Migration can proceed incrementally without a blind repository-wide enum rename.

### Trade-offs

- Consumers that currently rely on `ACKNOWLEDGED`, status-shaped `ExecutionOutcome` values, or the old mutable state machine need an explicit adaptation step.
- The normalized evidence contract adds a deliberate boundary between immutable source receipts/events and the aggregate lifecycle state.

## Scope exclusions

This ADR does not implement the reducer migration, change SQLite schemas, revise broker submission/cancel mechanics, add retry behavior, broaden LIVE capability, undertake package-wide moves, or introduce Flow/UI, a CLI, AI agents, scheduling, or new broker integrations. Those changes require their own scoped implementation and validation.
