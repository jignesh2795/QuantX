# QuantX Implementation

## Canonical documents

- `v0.1-build-order.md` — implementation sequence and release gates.
- `local-release-validation-playbook.md` — operator sequence for producing exact-head validation and release-gate evidence locally.
- `package-coverage-floors.md` — measured line/branch floors for `quantx.domain`, `quantx.execution` and `quantx.persistence`, with the baseline SHA, commands, new-module policy and revision policy.
- `p0-canonical-contracts.md` — stable internal vocabulary and invariants.
- `quarantine-evidence-worklist.md` — read-only operator view of unresolved quarantined submission evidence.
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

QX-08 M1–M4 and the normative T1–T8/G1–G3 acceptance reconciliation are complete on `main` through PRs #224, #226, #229, #232 and #234; issue #196 is closed. The canonical engine-truth context, callbacks/timers, engine-derived BuyAndHold, strict typed parameters/history bounds, and paper/backtest driver parity are established. Do not reopen QX-08 or describe M2/M3/M4 as pending. The callback-enabled path rejects nonzero execution-latency profiles rather than introducing an execution-event scheduler; expanding latency support remains deferred. The CLI remains deferred under ADR-008; REST/WebSocket remain behind M5/Gate 5. C13/C14 research persistence and provenance composition, v0.1 local-first host readiness, and the QX-03 canonical order lifecycle are completed baselines.

**M4.5 — Flow-to-existing-runtime parity is the active new strategy-platform vertical.** F4.5.1 is complete in [PR #317](https://github.com/jignesh2795/QuantX/pull/317), merged at `521fb6ed76dffc30d23d89333923dd6b81c6b293` from exact locally validated candidate `97d1647194405dbd778c51d38b6b92ee3190e154`; issue #316 is closed. Its first slice is the immutable typed/versioned Flow definition, canonical fingerprint, closed v1 node/port catalogue and pure graph validator. It does not implement a compiler/interpreter or `ExecutableStrategy` adapter. F4.5.2, the pure deterministic interpreter, is the next bounded slice. Flow execution, when separately implemented, must reuse `StrategyContext`, `StrategyRuntime`, deployment-owned binding, `StrategyExecutionPreparer`, risk/policy, and the existing offline paper/backtest consumers; no second runtime or direct broker/order path is permitted.

Execution/recovery internals remain stable unless a concrete invariant violation is demonstrated. Do not start broad package migration, UI/AI, distributed infrastructure, or a wider broker matrix without a specific roadmap gate and evidenced requirement.

## Batch history

Detailed batch history belongs in Git history and architecture consolidation records. Do not create one permanent document per batch unless it introduces a durable architectural decision.
