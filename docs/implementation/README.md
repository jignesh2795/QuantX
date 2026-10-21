# QuantX Implementation

## Canonical documents

- `v0.1-build-order.md` — implementation sequence and release gates.
- `local-release-validation-playbook.md` — operator sequence for producing exact-head validation and release-gate evidence locally.
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

QX-08 M1 is complete on `main` via PR #224 (validated feature head `0e9dd86401dae244b0c2546af528211a7039346d`, merge commit `8f1cc49c143fd5ee866be81fe366763700db1ac5`). M1 establishes immutable strategy context and engine-evidence foundations, typed parameters, strict prior-only history, event-time preflight contracts, and T8 boundary coverage; it does not add timer/callback dispatch or driver wiring. The next ordered strategy-platform implementation phase is QX-08 M2 under issue #196: callback/timer semantics, deterministic timer dispatch and cohort ordering, and G1/G2 failure/halt behavior. M3 then covers context-derived BuyAndHold and strict parameter/history bounds; M4 covers paper/backtest driver wiring and parity. Each phase is gated on its mapped tests at the exact reviewed SHA. The callback-enabled path rejects nonzero execution-latency profiles rather than introducing an execution-event scheduler; expanding latency support is deferred. The CLI remains deferred under ADR-008; REST/WebSocket remain behind M5/Gate 5. C13/C14 research persistence and provenance composition, v0.1 local-first host readiness, and the QX-03 canonical order lifecycle are completed baselines.

Execution/recovery internals remain stable unless a concrete invariant violation is demonstrated. Do not start broad package migration, UI/AI, distributed infrastructure, or a wider broker matrix without a specific roadmap gate and evidenced requirement.

## Batch history

Detailed batch history belongs in Git history and architecture consolidation records. Do not create one permanent document per batch unless it introduces a durable architectural decision.
