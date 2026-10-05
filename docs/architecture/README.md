# QuantX Architecture

This directory contains the architecture record for QuantX.

## Read first

1. `00-overview.md`, `01-principles.md`, `02-dependency-rules.md`
2. `05-execution-environments.md`, `06-indian-market-domain.md`, `07-data-control-execution-planes.md`, `08-strategy-ir.md`
3. `18-research-baseline.md`, `36-historical-data-integrity-and-no-hallucination.md`, `37-research-operational-integrity.md`, `39-research-provenance-and-fingerprints.md`, `40-point-in-time-market-rules.md`
4. `34-capital-and-routing-invariants.md`, `40-execution-reliability-and-transaction-safety.md`, `43-execution-transaction-boundary.md`, `44-execution-and-integration-package-boundaries.md`, `45-execution-reliability-batch.md`, `47-execution-audit-findings.md`, `47-integration-boundaries.md`, `49-dhan-broker-plugin-boundary.md`
5. `41-current-package-map.md`, `42-implementation-batch-plan.md`, `46-consolidation-status.md`

## Other architecture areas

Plugin model/contracts: `04-plugin-model.md`, `13-plugin-contract.md`.

Storage/message bus: `09-storage-and-message-bus.md`.

Security: `10-security-and-permissions.md`.

Testing: `11-testing-and-contracts.md`.

Deployment: `12-deployment-model.md`.

## Rules for future docs

- Prefer the latest explicit architecture document when older numbered records conflict.
- Do not create a new architecture file for every implementation batch.
- Refine an existing canonical document when possible.
- Put durable decisions in `docs/decisions/`.
- Put implementation sequencing in `docs/implementation/`.
- Put future milestones in `docs/roadmap/`.
- Keep historical records only when they explain the current architecture.

The numbered files are an architecture history/specification set, not dozens of independent active specifications.
