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

R1-C14 dataset ingestion/provenance composition is complete on `main`. The next focus is v0.1 local-first host and integration readiness, starting with an acceptance-criteria audit of the existing runtime, production composition, and entrypoints. Execution/recovery internals are considered stable unless a concrete invariant violation is demonstrated. Do not start broad package migration, UI/AI, distributed infrastructure, or a wider broker matrix while the existing integration path remains to be proven.

## Batch history

Detailed batch history belongs in Git history and architecture consolidation records. Do not create one permanent document per batch unless it introduces a durable architectural decision.
