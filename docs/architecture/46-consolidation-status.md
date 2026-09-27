# QuantX Architecture Consolidation Status

## Purpose

This document records the repository consolidation pass. The goal is to make the implementation match the agreed modular architecture without continuing to add parallel abstractions.

## Frozen architectural direction

QuantX is a modular trading/research platform with:

- market separation from the beginning: India, Global, Crypto;
- broker and venue implementations behind adapter/plugin boundaries;
- account and connection identity as first-class state;
- actual broker balance or explicitly configured paper balance as the capital source;
- broker/venue minimums enforced only when explicitly known;
- shared execution semantics across replay, paper, shadow and live modes where practical;
- deterministic historical replay with point-in-time rules and provenance;
- explicit unknown/incomplete states instead of fabricated values;
- idempotent order submission and broker reconciliation;
- AI as an optional intelligence layer, never a prerequisite for core correctness.

## Current top-level packages

```text
src/quantx/
├── domain/
├── execution/
├── integrations/
└── research/
```

These are the current implemented areas. Additional top-level packages such as `application`, `portfolio`, `risk`, `plugins`, `ai`, and `infrastructure` should be introduced when their implementation is actually ready, not merely to satisfy a diagram.

## Completed consolidation examples

### Idempotency

The package implementation is canonical:

```text
execution/idempotency/
├── __init__.py
├── fingerprint.py
└── store.py
```

The redundant flat `execution/idempotency.py` was removed.

### Execution receipts

The package implementation is canonical:

```text
execution/receipts/
├── __init__.py
└── models.py
```

The earlier flat `execution/receipts.py` was removed after its fields and compatibility names were consolidated into the package model.

### Integration reconciliation

The reconciliation package is now canonical:

```text
integrations/reconciliation/
├── __init__.py
├── account.py
├── orders.py
└── positions.py
```

The redundant flat implementations were removed:

- `integrations/account_state.py`
- `integrations/reconciliation.py`
- `integrations/order_reconciliation.py`
- `integrations/execution_preconditions.py`

Account and position state now use the domain's `AccountId` and `BrokerConnectionId` value objects. Execution readiness remains owned by `execution/preconditions/`; integrations supply observed account, position, broker, and health evidence.

### Batch-C: Dhan account/position evidence bridge

Reconciliation package consolidation is complete. The Dhan plugin now provides
normalized account and position observations through the canonical contracts:

- `DhanFundsSnapshot` / `DhanPositionsSnapshot` carry broker observations with
  no domain or vendor types; only `transport.py` imports `dhanhq`;
- `DhanBrokerAdapter.account_state()` maps observed balances to canonical
  `AccountFinancialState` (missing values stay `None`, never zero);
- `DhanBrokerAdapter.position_states()` reverse-resolves
  `(security_id, exchange_segment)` to canonical `InstrumentId` and returns
  canonical `PositionState` evidence;
- the plugin advertises `BALANCES` and `POSITIONS` alongside
  `ORDER_SUBMISSION` and `ORDER_CANCELLATION`.

Evidence flow:

```text
Dhan API
   ↓
Dhan transport
   ↓
Dhan normalized snapshot
   ↓
QuantX AccountFinancialState / PositionState
   ↓
Reconciliation
   ↓
Execution Preconditions
   ↓
READY / BLOCKED / UNKNOWN
```

Integrations provide evidence; execution preconditions consume it.
Missing or unmapped broker state remains fail-closed: unavailable observations
raise instead of returning empty state, and unknown evidence never produces an
execution-ready result. No live Dhan account connectivity was tested; all
verification uses the deterministic in-memory transport.

### Batch-C.6: reconciliation evidence refresh

`application/reconciliation.py` remains the canonical orchestration workflow
for one reconciliation evaluation. `application/evidence_refresh.py` is the
application-layer refresh coordinator. Canonical reconcilers remain pure
comparison components under `integrations/reconciliation/`.

Unresolved evidence can be refreshed only through an explicit provider
boundary. Definitive reconciliation requires the explicitly configured
evidence scope; the default scope requires order + position + account to all
be `MATCHED`. `UNKNOWN`, `STALE`, `INCOMPLETE`, and `UNAVAILABLE` remain
non-definitive until authoritative refreshed evidence resolves them.
Definitive `MISMATCH` is not automatically retried. Refresh attempts are
bounded by explicit policy. No broker-specific implementation is required by
the refresh coordinator, and no network/live broker behavior was added by C.6.

```text
Current reconciliation result
            ↓
Unresolved evidence
            ↓
ReconciliationEvidenceProvider
            ↓
Refreshed broker observation
            ↓
OrderStateReconciliationWorkflow
            ↓
Canonical reconciliation result
            ↓
Definitive only when required evidence is MATCHED
```

## Current migration policy

Existing flat modules are not automatically wrong. A module remains until its callers can be migrated safely. Compatibility wrappers are temporary and must not become permanent duplicate implementations.

## Next consolidation batch

Before adding another major trading subsystem:

1. inventory execution flat modules versus execution subpackages;
2. inventory integration flat modules versus integration subpackages;
3. inventory research modules and group them by responsibility;
4. identify duplicate contracts and imports;
5. migrate implementations, not just wrappers;
6. update tests with the implementation moves;
7. remove redundant modules only after callers are migrated;
8. run the test suite and record unresolved issues;
9. update this document to reflect the actual tree.

## Architectural quality gate

A new module should answer all of these:

- What single responsibility does it own?
- Why does that responsibility not belong in an existing module?
- Is it domain, application, execution, research, integration, plugin, AI, or infrastructure code?
- Can it be tested without a real broker?
- Does it preserve account and market identity?
- Does it preserve deterministic/provenance requirements where applicable?

If the answer is unclear, stop and consolidate rather than adding another abstraction.
