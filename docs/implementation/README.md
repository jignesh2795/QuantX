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

M4.1 deterministic strategy-to-paper rehearsal is complete on `main` via PR #218 (validated feature head `d99c12f3ae051f992722bee2bc8ea3253032fdc8`, merge commit `a0bf101b6f6bb87d11460cefb199932a768d6335`). It proves the existing Python strategy definition/IR/runtime path through explicit deployment-context binding, risk/policy preparation and the canonical paper executor. This is the first M4 vertical, not completion of M4 overall or proof of Python/Flow parity.

The next ordered design task is issue #197 (market-pack pre-trade-check pipeline); issue #196 specifies this design must precede expansion of the engine-truth StrategyContext/callback contract. The CLI remains deferred under ADR-008. REST/WebSocket remain behind M5/Gate 5. C13/C14 research persistence and provenance composition, v0.1 local-first host readiness, and the QX-03 canonical order lifecycle (PRs #213, #214 and #216) are completed baselines rather than pending next milestones.

Execution/recovery internals remain stable unless a concrete invariant violation is demonstrated. Do not start broad package migration, UI/AI, distributed infrastructure, or a wider broker matrix without a specific roadmap gate and evidenced requirement.

## Batch history

Detailed batch history belongs in Git history and architecture consolidation records. Do not create one permanent document per batch unless it introduces a durable architectural decision.
