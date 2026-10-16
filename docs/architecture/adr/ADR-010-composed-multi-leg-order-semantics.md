# ADR-010: Composed Multi-Leg Order Workflow Semantics

**Status:** Accepted (2026-10-16)

**Issue:** [#195 — QX-06 native basket versus composed multi-leg semantics](https://github.com/jignesh2795/QuantX/issues/195)
**Decision scope:** Architecture contract only. This ADR does not claim that multi-leg execution is implemented.

## Context

QuantX currently models an individual trading intent, approved execution request, order, receipt, fill, and canonical lifecycle. The existing receipt/request identity guard (QX-01) and canonical evidence-preserving order lifecycle (QX-03 / ADR-009) are per-order contracts. A multi-leg strategy such as a spread introduces additional aggregate concerns: stable leg ordering, workflow idempotency, joint risk and margin, partial fills, an uncertain outcome on one leg, and exposure remaining after another leg has completed.

The repository does not currently establish an atomic exchange/broker basket contract. A broker capability or adapter implementation must not be assumed to make multiple orders all-or-none. An application that emits several independent orders without an explicit workflow policy could leave a partially hedged or unhedged position after a rejection, partial fill, cancellation race, or UNKNOWN result.

## Decision

**The first supported multi-leg model will be a composed, application-owned workflow of ordinary single-leg orders. QuantX will not introduce a native basket aggregate or claim atomic basket execution in this milestone.**

The workflow is an orchestration and evidence boundary, not a second order lifecycle. Each leg remains a normal order that passes through the existing validation, risk/policy, reservation/idempotency, execution, receipt-validation, accounting, and canonical lifecycle paths. Existing lifecycle components remain authoritative for the state of each individual order.

This is a constrained design choice, not permission to execute multi-leg strategies immediately. Implementation must wait for the product/position-effect and derivative-contract decisions in issues #193 and #194, and for explicit aggregate-risk/reservation support. A workflow is unsupported and must fail closed when the existing platform cannot prove its admission and recovery requirements.

## Required contract

### 1. Workflow and leg identity

- A workflow has a stable caller/workflow identity and a canonical fingerprint. The fingerprint includes the ordered leg definitions and quantities, account/portfolio and deployment scope, strategy/version where applicable, market-pack and rule-snapshot identities, and any order attributes that change execution semantics.
- Each leg has a stable, unique `leg_id` and an explicit unique integer `sequence`. The workflow's dispatch order is the declared sequence; it must never be inferred from symbol sorting, hash/set iteration, arrival order, or a broker adapter.
- Each leg has its own ordinary order identity and idempotency key deterministically bound to the workflow identity and leg identity. Replaying the same workflow identity and fingerprint returns/continues the existing recorded workflow. Reusing the same workflow identity with a different fingerprint is rejected before side effects.
- The complete ordered leg set is validated before the first submission. Empty workflows, duplicate leg IDs/sequences, non-positive quantities, conflicting execution contexts, and malformed/incomplete instrument or contract details fail closed.
- Product and position effect are canonical per-leg order semantics, not instrument identity. Their concrete vocabulary and compatibility defaults are governed by QX-04 (#193). Derivative underlying, expiry, strike, and option type are governed by QX-05 (#194). This ADR does not invent provisional aliases or duplicate those contracts.

### 2. Admission, risk, and margin

- Admission is workflow-wide. Before any leg is submitted, the platform must validate every leg against the same declared market/rule context and a coherent point-in-time evidence cut, then evaluate the aggregate proposed portfolio impact.
- Risk evaluation must cover the **ordered execution path**, not only the desired final spread. The selected sequence and feasible partial-fill states can expose intermediate positions. The risk policy must establish that each attainable intermediate exposure allowed by the execution policy fits applicable risk, funds, and margin limits. If that path cannot be evaluated or authorized, reject the workflow before its first submission.
- Every leg must also pass the existing ordinary per-leg validation, pre-trade checks, policy, and execution reservation path immediately before submission. Workflow-wide authorization does not bypass per-leg gates.
- The implementation must have a durable workflow-level identity/state and a capacity/risk reservation or equivalent authorization that covers the admitted exposure path. Sequential per-order checks without aggregate admission are insufficient because individually acceptable orders can be unsafe in combination. If the current reservation contract cannot represent this safely, multi-leg dispatch remains unsupported until a separately reviewed extension is designed.
- The default margin calculation grants **no assumed spread or offset benefit**. A margin benefit may be applied only when an authoritative, effective-dated market-pack rule explicitly describes the applicable product/contract combination and the existing risk calculation can evaluate it. Missing or unsupported rule data must produce rejection/unavailable evidence, not a guessed margin amount.
- Native broker basket support, where a specific adapter may later document it, is not implied by this composed workflow decision and cannot weaken these platform-level controls.

### 3. Serialized dispatch and progression

- The first implementation is strictly sequential: one leg is submitted at a time, in explicit `sequence` order. Parallel submission is not supported.
- A subsequent leg may be submitted only after the current leg has a definitive, reconciled outcome satisfying the workflow's progression policy. An ACCEPTED/SUBMITTED/PENDING or otherwise still-live leg is not final and blocks dispatch of the next leg; this avoids silently advancing while the earlier leg may still fill.
- Full-fill progression requires validated receipts and fills whose aggregate quantity exactly meets that leg's requested quantity under the canonical lifecycle contract. A status label alone cannot manufacture fill evidence.
- A definitive rejection before any leg has created exposure stops the workflow with an explicit no-exposure failure outcome; later legs are not submitted.
- A partial fill, partial fill followed by cancellation/expiry, contradictory terminal evidence, or another incomplete leg outcome stops further dispatch. All known committed fills and order facts remain visible. The workflow is marked as partial exposure requiring reconciliation, and all not-yet-submitted legs are explicitly recorded as not submitted.
- An UNKNOWN or otherwise uncertain outcome after a submission may have reached the broker stops the workflow. The leg remains unresolved and is routed through the existing authoritative reconciliation boundary. There is no automatic retry, speculative rejection, or blind submission of another leg.
- If one or more earlier legs completed but a later leg definitively fails, preserve the known position/exposure and classify the workflow as partial exposure requiring reconciliation. Do not report success, erase completed legs, or imply that the intended hedge exists.
- Workflow completion is reported only when all required legs have definitive, reconciled outcomes satisfying the declared completion policy. The workflow must not claim exchange/broker atomicity or all-or-none fills.

### 4. Partial-exposure and recovery policy

The initial policy is **halt and preserve evidence; do not automatically compensate**.

- No automatic flatten, reverse, replacement, hedge, or other compensating order is emitted after a leg rejection, partial fill, or UNKNOWN result. A compensating trade is a new risk-bearing order and may itself fail or duplicate exposure if the original outcome is uncertain.
- The workflow becomes non-progressing until its current leg's status and fills are authoritatively resolved. Existing QX-01 receipt/request validation and ADR-009 lifecycle/reconciliation semantics remain in force.
- The result must expose, at minimum, workflow identity/fingerprint, explicit leg order, per-leg order identity and canonical status, validated fill facts and quantities, unsubmitted legs, unresolved/reconciliation requirement, known residual exposure, and the reason progression halted.
- Operational recovery beyond evidence reconciliation (for example, a user-approved flatten or strategy-specific hedge) is a separate explicitly authorized workflow. It is not part of automatic recovery, and this ADR does not invent a human approval interface or new live capability.
- Cancellation applies only through the existing canonical single-order cancellation/reconciliation semantics. Cancellation request acceptance is not proof that an order can no longer fill.

### 5. Determinism, persistence, and replay

- Leg sequence, workflow fingerprint, leg idempotency identity, and state transitions are stable and explicit. Equal-time facts use existing canonical event/evidence ordering, not wall-clock scheduling or adapter-defined ordering.
- Workflow and per-leg state must be durable enough to survive process restart and resume reconciliation without resubmitting already-dispatched legs. If the required durable linkage cannot be represented by existing persistence/idempotency seams, implementation must add a separately reviewed, bounded persistence design before enabling dispatch; an in-memory-only workflow is not sufficient.
- Every child receipt and fill is retained as authoritative evidence through existing receipt persistence, identity validation, lifecycle reduction, and accounting. Do not create a parallel receipt model, fill ledger, order lifecycle reducer, or independent idempotency store.
- Deterministic replay must reproduce the same leg sequence and intent/order identity for the same canonical input, workflow identity, and rule versions. A retry of an unresolved external submission is never inferred safe from replay determinism alone.

## Unsupported in the first vertical

- Native/atomic basket semantics or any claim that several broker orders commit all-or-none.
- Parallel submission of legs or adapter-defined leg ordering.
- Automatic flattening, hedging, reversal, replacement, or retry after uncertain submission.
- Assumed spread-margin offsets, unsupported product/contract combinations, or execution without a coherent aggregate risk assessment.
- Cross-broker or cross-account atomicity, dynamic leg reordering/resizing, conditional legs, recurring workflows, and a general-purpose saga/workflow engine.
- Introducing LIVE capabilities merely because the workflow can represent several legs.

## Alternatives considered

### Native basket aggregate — rejected for the first vertical

A native aggregate would need its own stable identity, capability semantics, child-order mapping, aggregate lifecycle, persistence/recovery contract, partial-leg failure behavior, risk/margin semantics, and broker-specific atomicity claims. The present order and receipt contracts do not establish those guarantees. Introducing an aggregate now would risk a second lifecycle model and imply capabilities that an adapter may not actually possess.

### Uncoordinated independent orders — rejected

Calling the existing single-order path repeatedly without a workflow identity, aggregate risk admission, deterministic sequence, and partial-exposure state would permit duplicate legs and hidden unhedged exposure. It does not satisfy the acceptance criteria.

### Automatic compensating orders — rejected

A compensating trade cannot safely be inferred from a failure callback or UNKNOWN receipt. The original leg may have filled despite missing/late confirmation; automatic reversal could create a second unintended position. Recovery requires authoritative reconciliation and a separately authorized decision.

## Consequences

**Benefits:** preserves the current per-order safety boundaries, keeps one canonical lifecycle and receipt model, makes ordering/replay/idempotency explicit, and represents partial exposure rather than disguising it as a successful spread.

**Costs and limitations:** intermediate unhedged exposure is possible by design and must be pre-admitted and surfaced; the workflow is not atomic; aggregate path-risk and durable workflow-state support are prerequisites; unsupported margin semantics cause fail-closed rejection. The initial workflow is deliberately less convenient than a broker basket but has clearer correctness guarantees.

## Implementation gates

Before implementation:

1. Complete QX-04 (#193) and QX-05 (#194) so each leg has canonical product/position-effect and derivative-contract identity.
2. Trace existing request fingerprints, reservation-before-submit, execution receipts, portfolio/margin checks, and durable recovery to define the smallest aggregate admission and workflow linkage without duplicate stores.
3. Specify how aggregate/path risk can account for partial fills and each intermediate exposure; document unsupported combinations explicitly.
4. Keep QX-07 package-boundary work (#181) sequenced after the contract ownership work already required by its issue.
5. Add deterministic local tests for duplicate workflow identity/fingerprint conflicts, stable leg order, whole-workflow admission before the first side effect, per-leg idempotency, partial-fill/rejection/UNKNOWN outcomes, preserved exposure, no automatic compensation/retry, restart/reconciliation, and repeatable replay.
6. Run exact-SHA local focused/full pytest, Ruff check/format, strict mypy with Dhan extra on and off, locked sync checks, and `git diff --check`. GitHub Actions is not treated as validation evidence while runner initialization is unavailable.

This ADR accepts the **composed workflow design only**. It closes the design-choice question in issue #195; it does not close the implementation gates or claim multi-leg execution is available.
