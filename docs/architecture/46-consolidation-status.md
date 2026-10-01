# QuantX Architecture Consolidation Status

## Purpose

This document records the repository consolidation pass and keeps implementation aligned with the agreed modular architecture without adding parallel abstractions.

## Current implementation status

The repository has progressed beyond the original Batch-28 documentation baseline.

```text
Validation reference: feat/continuation-claim-recovery-state-v1 at 7f73d1005b779fab253c5bda5cf308effe9140a5
Validation report: 594 passed, 0 failed, 0 errors, 0 skipped

The documentation-sync commits following that validation do not claim to change production behavior.
```

The active area is execution-integrity hardening, developer-validation integrity, and stack integration.

## Frozen architectural direction

- market separation: India, Global, Crypto;
- broker and venue implementations behind adapter/plugin boundaries;
- account and connection identity as first-class state;
- actual broker balance or explicitly configured paper balance as the capital source;
- broker/venue minimums enforced only when explicitly known;
- shared execution semantics across replay, paper, shadow and live modes where practical;
- deterministic historical replay with point-in-time rules and provenance;
- explicit unknown/incomplete states instead of fabricated values;
- idempotent order submission and broker reconciliation;
- AI as an optional intelligence layer, never a prerequisite for core correctness.

## Consolidation completed

### Idempotency

The canonical implementation is `execution/idempotency/` with request fingerprinting and storage contracts.

### Execution receipts

The canonical implementation is `execution/receipts/`, including immutable receipt models and lifecycle reconstruction.

### Integration reconciliation

The canonical reconciliation package is `integrations/reconciliation/`. Integrations provide observed evidence; execution preconditions decide whether evidence is sufficient for execution.

### Reconciliation evidence refresh

`application/evidence_refresh.py` is the application-layer refresh coordinator. Definitive reconciliation requires the configured evidence scope. `UNKNOWN`, `STALE`, `INCOMPLETE`, and `UNAVAILABLE` remain non-definitive until authoritative evidence resolves them. Refresh attempts are bounded by explicit policy.

### Continuation and recovery

Continuation is now a distinct execution responsibility:
- continuation requests derive from authoritative lifecycle remainder;
- child orders retain explicit parent lineage;
- continuation chains can be reconstructed from receipt evidence;
- aggregate fills cannot exceed root order quantity;
- continuation dispatch uses idempotency claims;
- recovery distinguishes `NOT_PENDING`, `PENDING`, `RECOVERABLE`, and `RESOLVED`;
- a reused claim must match authoritative receipt identity, quantity, account, and broker connection;
- contradictory or unresolved evidence is rejected rather than converted into a successful continuation.

The continuation boundary remains persistence-agnostic and does not introduce broker network behavior.

## Current migration policy

Existing standalone modules are not automatically wrong. A module remains valid when it owns one cohesive responsibility and its boundary is clearer than a forced subpackage migration.

Compatibility wrappers are temporary where they exist and must not become permanent duplicate implementations.

## Current LIVE-control hardening

The execution audit identified and addressed two final control-path gaps: LIVE execution now requires the recovery-backed `ApplicationRuntime` to have completed startup, and the trading gate now provides a submission permit that spans durable reservation and broker submission. The permit is synchronized across gate instances sharing the same state store; no database transaction is held across the broker call. Default reconciliation evidence now also requires broker-order account/connection scope, while narrower policies remain explicit opt-outs.

These controls preserve the existing modular boundaries: startup remains application composition, gate state remains execution control, and reconciliation remains evidence-based. No new generic runtime/router abstraction is introduced.

## Current consolidation gate

The earlier broad inventory/migration checklist is no longer the active next batch. Before introducing a new major subsystem:
1. confirm the proposed responsibility does not duplicate an existing boundary;
2. confirm account, connection, market, and instrument identity are preserved;
3. confirm unknown evidence remains explicit;
4. confirm deterministic/provenance requirements remain intact where applicable;
5. add focused regression coverage;
6. run the full validation suite;
7. update canonical status/architecture documentation if the boundary is durable.

## Architectural quality gate

A new module should answer:
- What single responsibility does it own?
- Why does that responsibility not belong in an existing module?
- Is it domain, application, execution, research, integration, plugin, AI, or infrastructure code?
- Can it be tested without a real broker?
- Does it preserve account and market identity?
- Does it preserve deterministic/provenance requirements where applicable?

If the answer is unclear, consolidate rather than adding another abstraction.