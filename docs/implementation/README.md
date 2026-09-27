# QuantX Implementation

## Canonical documents

- `v0.1-build-order.md` — implementation sequence and release gates.
- `p0-canonical-contracts.md` — stable internal vocabulary and invariants.
- `v0.1-repository-tree.md` — intended package/repository organization.

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

Execution integrity and reconciliation. Do not start a broad package migration or UI/AI subsystem while an existing boundary can be hardened incrementally.

## Batch history

Detailed batch history belongs in Git history and architecture consolidation records. Do not create one permanent document per batch unless it introduces a durable architectural decision.
