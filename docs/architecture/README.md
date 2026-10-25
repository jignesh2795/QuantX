# QuantX Architecture

This directory contains the architecture record for QuantX.

## Read first

1. `00-overview.md`, `01-principles.md`, `02-dependency-rules.md`
2. `05-execution-environments.md`, `06-indian-market-domain.md`, `07-data-control-execution-planes.md`, `08-strategy-ir.md`
3. `18-research-baseline.md`, `36-historical-data-integrity-and-no-hallucination.md`, `37-research-operational-integrity.md`, `39-research-provenance-and-fingerprints.md`, `40-point-in-time-market-rules.md`
4. `34-capital-and-routing-invariants.md`, `54-execution-reliability-and-transaction-safety.md`, `43-execution-transaction-boundary.md`, `44-execution-and-integration-package-boundaries.md`, `45-execution-reliability-batch.md`, `55-execution-audit-findings.md`, `56-live-execution-safety-audit-and-priority.md`, `57-live-risk-evidence-c1-contract.md`, `58-dhan-realized-daily-pnl-c2a-blocker.md`, `59-dhan-whole-account-position-evidence-c2b-blocker.md`, `47-integration-boundaries.md`, `49-dhan-broker-plugin-boundary.md`
5. `41-current-package-map.md`, `42-implementation-batch-plan.md`, `46-consolidation-status.md`, `51-historical-account-state.md`, `52-transaction-cost-and-charges.md`

## v0.1 release gate

`28-v0.1-acceptance-criteria.md` is the canonical v0.1 acceptance checklist. Its status table records the audited baseline; the open/closed release decision must follow the explicit release rule in that document rather than assuming all criteria pass.

## Other architecture areas

Architecture decisions: `adr/` holds accepted ADR-lite records explaining why the target shape exists (modular monolith, plugin-first extensibility, event-driven core, one semantic lifecycle, Indian-market-first domain, broker adapters, modular-hybrid topology). [ADR-010: Composed Multi-Leg Order Workflow Semantics](adr/ADR-010-composed-multi-leg-order-semantics.md) records the chosen multi-leg design; it is a design decision, not an implementation claim. [ADR-011: Order Product and Position Effect](adr/ADR-011-order-product-position-effect.md) records the QX-04 request-semantics contract; it is a design decision, not an implementation claim. [ADR-012: Derivative Contract Metadata and Resolution](adr/ADR-012-derivative-contract-metadata.md) records the QX-05 resolution contract; it is a design decision, not an implementation claim.

Execution control path: `control-and-safety-path.md` describes the ordered, fail-closed execution path from intent to portfolio update and is the reference for control-path safety review. The current audit and priority order for unresolved LIVE-safety gaps is tracked in `56-live-execution-safety-audit-and-priority.md` and issues #239–#241.

Plugin model/contracts: `04-plugin-model.md`, `13-plugin-contract.md`.

Storage/message bus: `09-storage-and-message-bus.md`.

Security: `10-security-and-permissions.md`.

Testing: `11-testing-and-contracts.md`.

Deployment: `12-deployment-model.md`.

## Rules for future docs

- Prefer the latest explicit architecture document when older numbered records conflict.
- Numbered architecture documents use unique, append-only numeric prefixes:
  a new document takes the next unused number (currently past `55-`),
  and an existing document is never renumbered to fill a gap. When a
  collision is found, the conflicting document moves to a new unused
  number, the index above and every inbound reference are updated, and
  the move is recorded with `git mv` so file history is preserved.
  (`40-execution-reliability-and-transaction-safety.md` → `54-…` and
  `47-execution-audit-findings.md` → `55-…` were resolved this way in
  issue #186. `40-package-organization-and-module-boundaries.md`,
  `40-point-in-time-market-rules.md`, and `47-integration-boundaries.md`
  keep their numbers because automation and skill references point at
  them.)
- Do not create a new architecture file for every implementation batch.
- Refine an existing canonical document when possible.
- Put durable decisions in `docs/decisions/`.
- Put implementation sequencing in `docs/implementation/`.
- Put future milestones in `docs/roadmap/`.
- Keep historical records only when they explain the current architecture.

The numbered files are an architecture history/specification set, not dozens of independent active specifications.

