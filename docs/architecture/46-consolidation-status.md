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

## Consolidation rule

For every responsibility, classify the existing implementation as:

1. KEEP - already in the correct canonical location.
2. MOVE - implementation belongs in another package.
3. MERGE - two implementations represent the same contract.
4. DELETE - redundant or superseded.
5. COMPATIBILITY - temporary wrapper required while callers migrate.

Do not create a second implementation merely because a cleaner package has been designed.

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
