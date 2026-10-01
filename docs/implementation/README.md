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
7. For the full contributor/test environment, install configured optional integration extras that are required by exercised tests (currently the Dhan extra).
8. Leave no unintended content changes.

OpenCode is the local validation harness; implementation changes are made on the project branch.

## Current focus

Developer validation must be reproducible from the documented uv setup. Optional integration dependencies required by the exercised full test suite belong in the documented contributor environment rather than in an individual validator's machine.

Execution integrity and reconciliation. Do not start a broad package migration or UI/AI subsystem while an existing boundary can be hardened incrementally.

## Batch history

Detailed batch history belongs in Git history and architecture consolidation records. Do not create one permanent document per batch unless it introduces a durable architectural decision.
