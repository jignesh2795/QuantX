# QuantX Architecture

This directory contains the architecture record for QuantX.

## Read first

1. [00-overview.md](00-overview.md), [01-principles.md](01-principles.md), [02-dependency-rules.md](02-dependency-rules.md).
2. [05-execution-environments.md](05-execution-environments.md), [06-indian-market-domain.md](06-indian-market-domain.md), [07-data-control-execution-planes.md](07-data-control-execution-planes.md), [08-strategy-ir.md](08-strategy-ir.md).
3. [18-research-baseline.md](18-research-baseline.md), [36-historical-data-integrity-and-no-hallucination.md](36-historical-data-integrity-and-no-hallucination.md), [37-research-operational-integrity.md](37-research-operational-integrity.md), [39-research-provenance-and-fingerprints.md](39-research-provenance-and-fingerprints.md), [40-point-in-time-market-rules.md](40-point-in-time-market-rules.md).
4. [34-capital-and-routing-invariants.md](34-capital-and-routing-invariants.md), [54-execution-reliability-and-transaction-safety.md](54-execution-reliability-and-transaction-safety.md), [43-execution-transaction-boundary.md](43-execution-transaction-boundary.md), [44-execution-and-integration-package-boundaries.md](44-execution-and-integration-package-boundaries.md), [45-execution-reliability-batch.md](45-execution-reliability-batch.md), [55-execution-audit-findings.md](55-execution-audit-findings.md), [56-live-execution-safety-audit-and-priority.md](56-live-execution-safety-audit-and-priority.md), [47-integration-boundaries.md](47-integration-boundaries.md), [49-dhan-broker-plugin-boundary.md](49-dhan-broker-plugin-boundary.md).
5. [41-current-package-map.md](41-current-package-map.md), [42-implementation-batch-plan.md](42-implementation-batch-plan.md), [46-consolidation-status.md](46-consolidation-status.md), [51-historical-account-state.md](51-historical-account-state.md), [52-transaction-cost-and-charges.md](52-transaction-cost-and-charges.md).

## v0.1 release gate

[28-v0.1-acceptance-criteria.md](28-v0.1-acceptance-criteria.md) is the canonical v0.1 acceptance checklist. Its status table records the audited baseline; the open/closed release decision must follow the explicit release rule in that document rather than assuming all criteria pass.

## Other architecture areas

- **Architecture decisions:** `adr/` holds accepted ADR-lite records explaining why the target shape exists (modular monolith, plugin-first extensibility, event-driven core, one semantic lifecycle, Indian-market-first domain, broker adapters, modular-hybrid topology).
- **Execution control path:** [control-and-safety-path.md](control-and-safety-path.md) describes the ordered, fail-closed execution path from intent to portfolio update. [56-live-execution-safety-audit-and-priority.md](56-live-execution-safety-audit-and-priority.md) preserves original audit history; its P0 findings #239–#241 are remediated and merged. Current unresolved LIVE risk/evidence and follow-up priorities are tracked in the [master work programme](../planning/quantx-work-program-2026-10.md) and issues #267, #266, #280, #271, #269 and #189.
- **Plugin model/contracts:** [04-plugin-model.md](04-plugin-model.md), [13-plugin-contract.md](13-plugin-contract.md).
- **Storage/message bus:** [09-storage-and-message-bus.md](09-storage-and-message-bus.md).
- **Security:** [10-security-and-permissions.md](10-security-and-permissions.md).
- **Testing:** [11-testing-and-contracts.md](11-testing-and-contracts.md).
- **Deployment:** [12-deployment-model.md](12-deployment-model.md).

## Core (00–09)

1. [00-overview.md](00-overview.md)
2. [01-principles.md](01-principles.md)
3. [02-dependency-rules.md](02-dependency-rules.md)
4. [03-branching-strategy.md](03-branching-strategy.md)
5. [04-plugin-model.md](04-plugin-model.md)
6. [05-execution-environments.md](05-execution-environments.md)
7. [06-indian-market-domain.md](06-indian-market-domain.md)
8. [07-data-control-execution-planes.md](07-data-control-execution-planes.md)
9. [08-strategy-ir.md](08-strategy-ir.md)
10. [09-storage-and-message-bus.md](09-storage-and-message-bus.md)

## Domain and execution (10–29)

1. [10-security-and-permissions.md](10-security-and-permissions.md)
2. [11-testing-and-contracts.md](11-testing-and-contracts.md)
3. [12-deployment-model.md](12-deployment-model.md)
4. [13-plugin-contract.md](13-plugin-contract.md)
5. [14-next-work.md](14-next-work.md)
6. [15-review-checklist.md](15-review-checklist.md)
7. [16-architecture-status.md](16-architecture-status.md)
8. [17-roadmap-alignment.md](17-roadmap-alignment.md)
9. [18-research-baseline.md](18-research-baseline.md)
10. [19-freeze-point.md](19-freeze-point.md)
11. [20-todo.md](20-todo.md)
12. [21-branching-status.md](21-branching-status.md)
13. [22-branch-instructions.md](22-branch-instructions.md)
14. [28-v0.1-acceptance-criteria.md](28-v0.1-acceptance-criteria.md)

## Advanced (30–56)

1. [32-global-market-separation.md](32-global-market-separation.md)
2. [33-capital-source-and-broker-constraints.md](33-capital-source-and-broker-constraints.md)
3. [34-capital-and-routing-invariants.md](34-capital-and-routing-invariants.md)
4. [35-paper-execution-realism.md](35-paper-execution-realism.md)
5. [36-historical-data-integrity-and-no-hallucination.md](36-historical-data-integrity-and-no-hallucination.md)
6. [37-research-operational-integrity.md](37-research-operational-integrity.md)
7. [38-paper-execution-and-research-fidelity.md](38-paper-execution-and-research-fidelity.md)
8. [39-research-provenance-and-fingerprints.md](39-research-provenance-and-fingerprints.md)
9. [40-package-organization-and-module-boundaries.md](40-package-organization-and-module-boundaries.md)
10. [40-point-in-time-market-rules.md](40-point-in-time-market-rules.md)
11. [41-current-package-map.md](41-current-package-map.md)
12. [42-implementation-batch-plan.md](42-implementation-batch-plan.md)
13. [43-execution-transaction-boundary.md](43-execution-transaction-boundary.md)
14. [44-execution-and-integration-package-boundaries.md](44-execution-and-integration-package-boundaries.md)
15. [45-execution-reliability-batch.md](45-execution-reliability-batch.md)
16. [46-consolidation-status.md](46-consolidation-status.md)
17. [47-integration-boundaries.md](47-integration-boundaries.md)
18. [48-quantumtrade-v1.6-migration-map.md](48-quantumtrade-v1.6-migration-map.md)
19. [49-dhan-broker-plugin-boundary.md](49-dhan-broker-plugin-boundary.md)
20. [50-production-host-integration-boundary.md](50-production-host-integration-boundary.md)
21. [51-historical-account-state.md](51-historical-account-state.md)
22. [52-transaction-cost-and-charges.md](52-transaction-cost-and-charges.md)
23. [53-deterministic-time-source-inventory.md](53-deterministic-time-source-inventory.md)
24. [54-execution-reliability-and-transaction-safety.md](54-execution-reliability-and-transaction-safety.md)
25. [55-execution-audit-findings.md](55-execution-audit-findings.md)
26. [56-live-execution-safety-audit-and-priority.md](56-live-execution-safety-audit-and-priority.md)

## Rules for future docs

- Prefer the latest explicit architecture document when older numbered records conflict.
- Numbered architecture documents use unique, append-only numeric prefixes. Gaps remain intentional; existing files are never renumbered to fill a gap. When a collision is found, a conflicting document moves to a new unused number only with all inbound references updated and a history-preserving move.
- The two existing `40-` records retain their names and numbers because automation and skill references point at them.
- Do not create a new architecture file for every implementation batch.
- Refine an existing canonical document when possible.
- Put durable decisions in `docs/decisions/`.
- Put implementation sequencing in `docs/implementation/`.
- Put future milestones in `docs/roadmap/`.
- Keep historical records only when they explain the current architecture.

The numbered files are an architecture history/specification set, not dozens of independent active specifications.
