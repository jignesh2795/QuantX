# QuantX Implementation

## Canonical documents

- `v0.1-build-order.md` — implementation sequence and release gates.
- `p0-canonical-contracts.md` — stable internal vocabulary and invariants.
- `v0.1-repository-tree.md` — historical v0.1 target tree; it is not the current source tree.

For the actual current package layout, use `docs/architecture/41-current-package-map.md`.

## Implementation discipline

1. Inspect existing code before changing it.
2. Identify one concrete integrity gap.
3. Make the smallest non-duplicative production change.
4. Add a focused regression test.
5. Run focused and full validation.
6. Run Ruff/format/mypy where applicable.
7. Leave no unintended content changes.

OpenCode is the local validation harness; implementation changes are made on the project branch.

## Current focus

R1-C14 dataset ingestion/provenance composition is complete on `main`. V0.1 local-first host and integration readiness is acceptance-complete for the declared programmatic-library scope (ADR-008; criteria and evidence in `docs/architecture/28-v0.1-acceptance-criteria.md`, current state in `docs/STATUS.md`), and the QX-03 canonical order lifecycle is implemented on `main` (ADR-009; PR #214 with the PR #216 receipt evidence-kind contract). Execution/recovery internals are considered stable unless a concrete invariant violation is demonstrated. Do not start broad package migration, UI/AI, distributed infrastructure, or a wider broker matrix while the existing integration path remains to be proven.

## Batch history

Detailed batch history belongs in Git history and architecture consolidation records. Do not create one permanent document per batch unless it introduces a durable architectural decision.
