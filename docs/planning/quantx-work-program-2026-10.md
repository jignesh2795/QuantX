# QuantX Master Work Programme — October/November 2026

**Status:** Active cross-workstream sequencing and reconciliation record

**Snapshot date:** 2026-11-09

**Baseline reviewed for this closeout:** `main` at `a620b3b13f2cd10c9fee19f61e3afd3121f345ff` (current main; PR #329 is an open draft based on this exact commit and is not merged).

**Purpose:** Keep prior architecture, safety, India-market realism, global-market research, strategy/research delivery, and release-readiness work in one progressable plan.

This is the canonical **active sequencing** document. GitHub issues remain the canonical individual acceptance/checklist records; `docs/STATUS.md` remains the implementation/evidence ledger; `docs/roadmap/README.md` remains the capability and milestone history. When an older status snapshot or planning note conflicts with the current issue acceptance criteria or this priority order, reconcile it before implementing. Do not infer completion from a branch name, documentation, or an old test count.

## 1. Repository snapshot and governance

- Latest `main` baseline used for this programme update: `a620b3b13f2cd10c9fee19f61e3afd3121f345ff` (current main; PR #329 remains an open draft on a separate branch).
- PR #314 merged as `99d64996214482a8443ca673f11fbb3b61bdc519`; PR #315 merged the pinned global architecture comparison as `0f4214e482c682fe99d133381cd1ef8d62b1492f`; PR #317 merged F4.5.1, PR #320 merged F4.5.2, PR #321 merged F4.5.3, and PR #324 merged F4.5.4 (merge `4a1a5f7629fff832dcec74471dae096f2d231733`; validated candidate `3b0566988ed336034b93d0782ec3a693aca3f153`); PR #325 merged the subsequent documentation reconciliation at `d2442bbbafab3eca91f27a8c3d8fdd65e3f61b80`.
- PR #309 is merged; PR #295 is a stale superseded migration candidate; PR #308 is a stale draft whose useful facts are incorporated in the current status; PR #306 remains a draft public-API candidate and is not validated on current main.
- This programme is refreshed after PR #325. F4.5.1–F4.5.4 are complete and issue #322 is closed. The parent M4 exit criterion is now reconciled as met; M4 is complete at the milestone level. The exact candidate validation and two unchanged Markdown Ruff-format baseline findings are recorded in PR #324 as local/operator-reported results, not hosted CI. No broker call, sandbox run or LIVE operation is claimed.
- **Current #200 slice:** PR [#329](https://github.com/jignesh2795/QuantX/pull/329) is an open draft on `feat/issue200-india-charge-contract-v1`, based on `a620b3b13f2cd10c9fee19f61e3afd3121f345ff`, with current HEAD `ce0f19ed046fb99e9bb45e248eda7ee6dad66367`. It contains a bounded India-specific contract implementation using synthetic schedules, not production tariffs or paper/research wiring. The PR body records full-suite, lint, type, coverage and release-gate results at parent code commit `58f3edffb5c46297837cfc99d8d19bf56a43ec0a` as operator-reported evidence; two documentation-only commits followed. The current HEAD still requires both canonical exact-SHA producer runs and both release gates. The March 1, 2026 transaction-charge/IPFT aggregate-preservation T21 acceptance test remains open. Issue #200 remains OPEN; the slice is not a completed issue.

**Work rules:** use one coherent branch/PR per implementation slice; record exact base and candidate SHAs; keep validation evidence tied to its tested SHA; run the declared local validation gates with Dhan extra both enabled and disabled where applicable; distinguish local/operator-reported results from GitHub Actions; do not merge implementation without exact-SHA evidence and required review. UNKNOWN and missing authoritative evidence are never PASS.

## 2. Completed work — do not redo without a new finding

| Workstream | Current disposition | Evidence |
|---|---|---|
| QX-01 receipt/request identity (#191) and QX-02 lifecycle/UNKNOWN handling (#185) | Implemented and merged | Recorded in `docs/STATUS.md` and tracker #207 |
| P0.1 durable trading gate (#239) | Implemented and merged | PR #243 |
| P0.2 startup recovery readiness (#240) | Implemented and merged | PR #244 |
| P0.3 post-submit uncertainty evidence (#241) | Implemented and merged | PR #247; do not reimplement absent a new defect |
| QX-04 product and position-effect contract (#193) | Implemented and merged | PR #250; ADR-011 |
| QX-05 derivative contract metadata/resolution (#194) | Implemented and merged | PR #252; ADR-012 |
| QX-07 dependency ownership (#181) | Slices 1, 2A and 2B merged; issue #181 closed on 2026-10-27 after verification | PRs #257, #259, #261; Slice 2B merge `8f86f8f8893261c414874bac09f75185f5ed5dd5` |
| QX-08 StrategyContext/callback sequence (#196) | Completed | PR sequence recorded in `docs/STATUS.md` |
| QX-09 market-pack pre-trade pipeline (#197) | Completed | PR #221 |
| QX-13 finite Decimal-only Money (#201) | Implemented and merged | PR #310; validated feature HEAD `24e3a3bc6205c6d8d5f7733d63c79a2ce94b0617`; squash merge `a2007f6a04859368608a42cd3898244382151a5a` |
| Open-source onboarding overview (#187/#204) | **Completed** | `CONTRIBUTING.md`, `ARCHITECTURE.md`, and credential-free `examples/paper_smoke.py`; issues #187 and #204 closed. |
| PR #307 Dhan statement observations | **Merged; supplemental/read-only only** | Merge `93ae5d0be0dec94308d85856c58a5e2f7be0eca2`; ledger/trade-history transport is not account/day P&L or LIVE authority. |
| Market-module migration (#309, bounded architecture slice) | **Implemented and merged** | PR #309; validated candidate `a3e52478e4cceef05e42d424048c51289f435020`; squash merge `8fd82b52e47cfaedd60f7df8aa30553636fa9d82`. India is the only implemented module; digital assets remains a placeholder; LIVE unchanged. |
| LIVE trusted-clock freshness and request-bound authority foundation | Implemented; evidence-source feasibility remains open | PR #281 plus #267 composition/request-binding controls; PRs #285/#307 add supplemental/read-only Dhan observations only. |
| QX-06 multi-leg semantics (#195) | **Design only**; no multi-leg execution implementation or capability claim | ADR-010; keep partial-leg failure and exposure semantics explicit |
| Pinned global architecture comparison | **Completed and merged** | PR #315; merge `0f4214e482c682fe99d133381cd1ef8d62b1492f`; final validated candidate `4fc030d41ba8767a64b2133acd6888b1b0d08c3f`. Exact upstream revisions and source/test paths are recorded in `docs/research/2026-11-global-architecture-comparison.md`. |
| M4 Strategy Platform parent milestone | **Complete against the single documented exit criterion** | M4.1 PR #218; QX-09/#197 PR #221; QX-08/#196 PRs #224/#226/#229/#232 and acceptance closeout #234; Flow parity/integration PRs #317/#320/#321/#324. |

QX-07 closure is a current update that supersedes the pre-merge snapshot still preserved in historical sections of `docs/STATUS.md`. The final slice's recorded local candidate validation was default **2,695 passed / 1 skipped** and Dhan-enabled **2,696 passed**, with Ruff/format, strict mypy, and independent review recorded as passing. These results belong to candidate SHA `a5219cf7616f34483e3c596d3feb47ac4c00673f`; they are local evidence, not GitHub Actions evidence, and do not establish production-broker or LIVE readiness.

## 3. Active priority order

Use the waves below as sequence, not as a commitment to implement every issue in one PR. Each issue retains its own acceptance criteria and scope.

**Sequencing deviation — 2026-11-09:** The canonical order below placed Wave C2 / #202 ahead of Wave D / #200. Current activity advanced one bounded, contract-only #200 slice first in PR #329. Treat this as a limited work-order deviation, not a reprioritization of the programme and not a change to the full #200 acceptance criteria. Finish the exact-SHA validation and evidence-based disposition of PR #329 first; after that bounded slice is resolved, #202 resumes as the next programme priority. #200 must remain open while authoritative tariff sourcing, golden published-rate examples and other issue-level acceptance items remain incomplete.

### Strategy Platform — M4.5 (completed bounded vertical)

| Slice | State | Next required outcome |
|---|---|---|
| **F4.5.1 — Flow definition and graph validation** | **Complete; [PR #317](https://github.com/jignesh2795/QuantX/pull/317) merged** | Validated candidate `97d1647194405dbd778c51d38b6b92ee3190e154`; merge `521fb6ed76dffc30d23d89333923dd6b81c6b293`; issue #316 closed. Immutable typed/versioned contract, canonical identity, closed v1 catalogue and pure validator. |
| **F4.5.2 — deterministic Flow compiler/interpreter** | **Complete; [PR #320](https://github.com/jignesh2795/QuantX/pull/320) merged** | Validated candidate `cea48214db4089efa0361fb5e3bc05e5818aeb5f`; merge `c659d4eb3d5aee74b78003cc9dfd112287bb78d6`; issue #319 closed. Immutable deterministic plans and pure Flow v1 evaluation. |
| **F4.5.3 — existing runtime adapter and parity** | **Complete; [PR #321](https://github.com/jignesh2795/QuantX/pull/321) merged** | Validated candidate `966fce2d32d4b9609aeb0d88ed2250e6af301881`; merge `a27b93f56f978b56a9d3a3373d8221d40ad6fd81`. Reuses `ExecutableStrategy`, `StrategyRuntime` and the existing `StrategyRegistry`; exact-SHA local tests and candidate-specific Ruff gates passed. |
| **F4.5.4 — offline PAPER/BACKTEST integration** | **Complete; [PR #324](https://github.com/jignesh2795/QuantX/pull/324) merged** | Validated candidate `3b0566988ed336034b93d0782ec3a693aca3f153`; merge `4a1a5f7629fff832dcec74471dae096f2d231733`; issue #322 closed. Test-only proof through canonical rehearsal and backtest consumers with fail-closed risk/policy outcomes and no LIVE path. |

QX-08 M1–M4 and its T1–T8/G1–G3 acceptance reconciliation remain complete. M4.5 is a separate parent-M4 product vertical; do not reopen QX-08 or duplicate the Python runtime.


### Wave A — LIVE risk authority and loss correctness

| Rank | Issue | State / next required outcome |
|---|---|---|
| **A1 — blocked pending provider** | [#267 LIVE risk evaluator authority and request-bound evidence](https://github.com/jignesh2795/QuantX/issues/267) | The application-owned composition, trusted clock, exact request/account/portfolio/connection binding, provenance checks and pre-reservation fail-closed rejection are implemented. The Dhan field-by-field feasibility matrix is already documented in the #267 issue history (2026-11-05); a current-main adapter inventory audit (2026-11-06, baseline `41550505922a294daef4c6aa73fb4c8420b42ab8`, with no adapter/LIVE-source changes through main `8fd82b52e47cfaedd60f7df8aa30553636fa9d82`) found only Dhan and Reference Broker adapters. Dhan declares zero supported fields; Reference Broker does not implement the evidence-source provider contract. No currently registered provider can supply the mandatory set. Keep the pre-collection block. Resume only when a credible alternative provider or materially new authoritative source is selected; then verify official source semantics, identity binding, completeness/pagination, source timestamps/freshness, precision, contradictions and regressions before any source implementation. Do not repeat the Dhan matrix or build another Dhan-specific wrapper absent new source capability. |
| A2 — contract defined; source feasibility blocked | [#266 LIVE daily-loss limit only sees realized P&L](https://github.com/jignesh2795/QuantX/issues/266) | Accounting semantics are documented in [PR #312](https://github.com/jignesh2795/QuantX/pull/312), merged at `71e407f8847d6866d4c893da271441f1adeaf2ed`. The 2026-11-06 read-only inventory at that main SHA found **0/7 required** Dhan fixtures, with optional `traders_diary_summary.json` also absent; cross-file completeness and source feasibility are not established. Do not attempt static reconciliation or implement account/session equity from absent evidence. Revisit only when a coherent, lawfully obtained, redacted fixture set or a separately evaluated authoritative source becomes available. Preserve realized-only `daily_pnl`, current `max_drawdown`, and #267's fail-closed LIVE boundary; #266 remains open. |
| Completed | [#280 preserve operator block reason at startup](https://github.com/jignesh2795/QuantX/issues/280) — [PR #287](https://github.com/jignesh2795/QuantX/pull/287) | Merged at `b290802f4331d4137d3bda407d12a95750d7e6b4`. Preserves existing disabled reasons; durably disarms enabled/fresh states; fails closed on gate-state read or required persistence failures. Exact-SHA default and Dhan validation plus both release gates passed. |
| Completed | [#189 Dhan startup/shutdown cleanup audit](https://github.com/jignesh2795/QuantX/issues/189) | Closed after cleanup-failure visibility and primary-exception preservation work. Do not repeat without a new defect. |

### Wave B — Strict boundary and deterministic-time hardening

| Rank | Issue | Next required outcome |
|---|---|---|
| Completed | [#271 exact UUID and Order runtime invariants](https://github.com/jignesh2795/QuantX/issues/271) | Closed after exact runtime-type enforcement and regression coverage; do not reintroduce coercion. |
| Completed | [#269 exact LIVE broker-probe validation](https://github.com/jignesh2795/QuantX/issues/269) | Closed; exact boolean/object probe validation and fixed fail-closed reasons are complete. |
| Completed | [#198 complete clock injection](https://github.com/jignesh2795/QuantX/issues/198) | Closed; behaviorally significant clock boundaries and deterministic replay requirements are addressed. |

### Wave C — Regression assurance

| Rank | Issue | Next required outcome |
|---|---|---|
| Completed | [#182 measured package-specific coverage floors](https://github.com/jignesh2795/QuantX/issues/182) | Domain, execution and persistence line/branch floors and the local validation/release gates are implemented; thresholds and methodology are recorded in `docs/implementation/package-coverage-floors.md`. |
| C2 | [#202 dead-module and Dhan transport coverage audit](https://github.com/jignesh2795/QuantX/issues/202) | Re-measure usage and line/branch coverage first; remove or justify suspected unused seams; improve deterministic transport tests without network access or inferred submit/cancel outcomes. |

### Wave D — India-market realism and public contract

| Rank | Issue | Next required outcome |
|---|---|---|
| D1 | [#200 effective-dated India charges schedule](https://github.com/jignesh2795/QuantX/issues/200) | **Contract-only slice in progress; [PR #329](https://github.com/jignesh2795/QuantX/pull/329) is draft and unmerged.** The bounded API/schedule implementation uses synthetic fixtures and explicit caller-supplied inputs; it does not establish production rates, a production schedule loader, golden published-rate examples, or PAPER/RESEARCH wiring. The current PR HEAD `ce0f19ed046fb99e9bb45e248eda7ee6dad66367` still needs exact-SHA default/Dhan validation and both release gates; earlier green evidence is operator-reported at parent code SHA `58f3edffb5c46297837cfc99d8d19bf56a43ec0a`. T21 aggregate-preservation acceptance remains open. Keep issue #200 OPEN; GST/stamp-duty applicability and source/effective-date evidence remain data gates. |
| Completed | [#201 finite Decimal-only Money](https://github.com/jignesh2795/QuantX/issues/201) | PR #310; validated candidate `24e3a3bc6205c6d8d5f7733d63c79a2ce94b0617`; squash merge `a2007f6a04859368608a42cd3898244382151a5a`. |
| D3 | [#199 curated provisional public API](https://github.com/jignesh2795/QuantX/issues/199) | Define a small `quantx.api` with explicit stability tiers; don't mass re-export internals or import optional Dhan SDKs at import time. |

The charges contract/design is available in `docs/planning/india-market-charges-design.md`; source and unresolved rule evidence are recorded in `docs/planning/risk-charges-evidence-reconciliation.md`. These documents are design/research inputs only. The original risk/charges note proposed a different ordering; its final sequence is now explicitly superseded here. Do not treat a label such as `BROKER` or `RECONCILED` as proof of authority.

### Wave E — Integration proof, ecosystem and public readiness

| Rank | Issue / workstream | Next required outcome |
|---|---|---|
| E1 | [#203 Dhan sandbox lifecycle evidence](https://github.com/jignesh2795/QuantX/issues/203) | Only when sandbox access is safely available; produce replayable evidence fixtures and preserve a strict no-real-capital boundary. |
| E2 | [#206 broker/market-data conformance and schemas](https://github.com/jignesh2795/QuantX/issues/206) | Reusable contract suites and versioned schemas; keep provider capabilities explicit. |
| Completed | [#188 StrategySignal confidence contract](https://github.com/jignesh2795/QuantX/issues/188) | Confidence remains a bounded strategy score, not a calibrated probability absent calibration evidence. Issue closed. |
| E3 | [#190 security reporting policy](https://github.com/jignesh2795/QuantX/issues/190) | Add a truthful private disclosure path only after confirming/configuring GitHub private vulnerability reporting or another real channel. Until then, do not invent contact details, SLA, bounty or supported-version policy; complete before broad public contributor recruitment. |
| Completed | [#204 architecture overview and quickstart](https://github.com/jignesh2795/QuantX/issues/204), [#187 CONTRIBUTING.md](https://github.com/jignesh2795/QuantX/issues/187) | `ARCHITECTURE.md`, `CONTRIBUTING.md` and a credential-free local paper smoke example are present; both issues closed. A dedicated `docs/GETTING_STARTED.md` remains a presentation-plan follow-up. |
| E5 | [#205 Python 3.13 validation](https://github.com/jignesh2795/QuantX/issues/205) | **Blocked/deferred:** keep `requires-python >=3.12,<3.13` until a reliable, actually executing validation runner exists. No GitHub Actions or paid CI under current project constraints. |

Issue [#207](https://github.com/jignesh2795/QuantX/issues/207) remains the meta review tracker; keep it updated as these workstreams move.

## 4. Global market and crypto work — research completed; implementation remains deferred

The pinned-source comparison in [`docs/research/2026-11-global-architecture-comparison.md`](../research/2026-11-global-architecture-comparison.md) completes this research deliverable. It records source revisions, implementation/test paths, QuantX equivalents and adopt/adapt/defer/reject decisions for LEAN, NautilusTrader, Hummingbot, OpenAlgo, CCXT and official Indian broker SDKs.

The comparison does **not** establish global-market, crypto or additional broker support. The market-module migration remains merged; India is still the only implemented market and the digital-assets module remains interface-only. The global architecture and crypto proposals remain unmerged design references. Do not merge them wholesale, split the repository or broaden India-only LIVE policy.

### Research conclusion and next bounded vertical

The data/research/provenance spine is complete through R1-C14. The Strategy Platform parent M4 is now complete against the canonical exit criterion: the Python path from M4.1/QX-08 and the first Flow path from M4.5 share the same `StrategyRuntime`/`StrategyResult` semantics and have offline PAPER/BACKTEST integration evidence.

**Current Strategy Platform disposition: M4 COMPLETE.** M4.5 F4.5.1–F4.5.4 are merged in PRs #317, #320, #321 and #324; PR #324 merged at `4a1a5f7629fff832dcec74471dae096f2d231733` from exact-SHA validated candidate `3b0566988ed336034b93d0782ec3a693aca3f153`, and issue #322 is closed. PR #321 supplies the shared-runtime adapter and Python/Flow semantic-result parity test; PR #324 proves deployment binding, preparation, risk/policy and the existing offline PAPER/BACKTEST consumers. This meets the sole M4 exit criterion in `docs/roadmap/milestones.md`. Visual Flow editing/persistence, external scheduling, webhooks/external signals, streaming, AI/cloud and cross-market/LIVE capabilities remain later/deferred platform work, not M4 blockers. No new F4.5.5 is proposed.

### Still blocked or deferred

- **#267:** blocked pending credible alternative authoritative source/provider evidence; keep the existing pre-collection/no-reservation/no-submit boundary.
- **#266:** blocked on the missing 0/7 required Dhan fixture set; do not infer account/session equity.
- **CCXT / digital assets / international venues:** deferred until a specific product demand, market scope, data/API access and separate market/LIVE eligibility review exist.
- **#206 conformance suites and schemas:** after #199 defines the public API/testing stability policy; do not duplicate provider contract definitions.

## 5. Project presentation and public readiness

The presentation plan is **partially complete**. Separate implementation from public claims:

| Area | Current state | Remaining action |
|---|---|---|
| Human contributor and architecture entry | **Completed** — #187/#204 closed; `CONTRIBUTING.md`, `ARCHITECTURE.md` and `examples/paper_smoke.py` exist. | Keep paths/commands aligned with current code; a dedicated `docs/GETTING_STARTED.md` is still useful but not a release blocker. |
| Curated Python API | **Open** — #199; PR #306 is draft, based on an older main and has no exact-head local validation. | Reconcile the branch on current main after the market migration, review the proposed exports and stability tiers, then run exact-SHA default/Dhan validation. Do not merge or claim public API stability yet. |
| Security disclosure | **Open** — #190; `SECURITY.md` absent. | Verify/configure a real private vulnerability-reporting path before publishing a policy. Never invent an email, SLA, bounty or supported-version statement. |
| Community files | `CODE_OF_CONDUCT.md` and `CHANGELOG.md` are absent. | Add only as part of an intentional contributor/release-preparation slice; the changelog must reflect actual release history. |
| README and package metadata | Current text still says Indian markets; `pyproject.toml` still has the India-market description. | Reconcile product wording to “India-first, market-neutral architecture” without implying global connectors. Verify links and supported Python range. |
| Status history/navigation | `docs/STATUS.md` remains over 1,000 lines; it contains useful history. | Later split into concise current status plus `docs/STATUS_HISTORY.md`, preserving all historical entries, anchors and links. Do not delete history or perform a mass docs move. |
| CI presentation | GitHub Actions/paid CI remains unavailable by project policy. | Do not add badges or claim CI is green. Use local exact-SHA validation. |

Issue #206 conformance tests and versioned schemas should follow #199's stability policy so test helpers and schema compatibility do not become an accidental public API. #203 remains conditional on safe sandbox access; #205 remains blocked pending a reliable validation runner.

## 6. Progress protocol

For every implementation slice:

1. Read this programme, the relevant current issue, `docs/STATUS.md`, the architecture index, and the actual source/tests being touched.
2. Verify whether the work is already merged or the issue/status is stale before creating new work. One task, one bounded branch/PR; no redundant reimplementation of completed P0/QX slices.
3. State the exact base SHA, acceptance matrix, changed-path boundary and no-claims before validation.
4. Run focused tests, full suite, Ruff/format, strict mypy, diff checks and the repo's validation/release gate as applicable. Run with Dhan extra enabled and disabled when required. Capture real exit codes; no masked failures.
5. Obtain adversarial review for execution, persistence, risk, time or market-rule changes. Validation results attach only to the exact tested candidate SHA. GitHub Actions/CI is mentioned only when an actual relevant run exists.
6. After merge, reconcile the issue, update the appropriate section in `docs/STATUS.md`, record exact merge/candidate SHAs, and update this programme's status/next step. Keep dated historical snapshots but label them historical; do not leave a pre-merge “current” snapshot unqualified.

## 7. Parent M4 exit reconciliation — complete

### Canonical criterion

The canonical M4 milestone definition in `docs/roadmap/milestones.md` has one exit criterion: **Python strategies and a first Flow path compile to the same runtime semantics.** This criterion is **MET**. It does not require every later strategy-platform surface to exist.

### Evidence mapping

| Criterion / prerequisite | Merged implementation and evidence | Disposition |
|---|---|---|
| Python strategy definition, IR, registry/runtime and offline PAPER path | M4.1 in PR #218; deterministic deployment-owned context binding, preparation, risk/policy and paper rehearsal. | Complete |
| Engine-truth context, deterministic callbacks/timers, engine-derived BuyAndHold and paper/backtest driver parity | QX-08/#196 M1–M4 in PRs #224, #226, #229 and #232; normative T1–T8/G1–G3 acceptance closeout in PR #234; issue #196 closed. | Complete |
| Market-pack pre-trade pipeline prerequisite | QX-09/#197 in PR #221; issue #197 closed. | Complete |
| First Flow path and semantic parity | F4.5.1 contract/validator PR #317; F4.5.2 compiler/interpreter PR #320; F4.5.3 `FlowExecutableStrategy` adapter through the existing `ExecutableStrategy`/`StrategyRuntime` path in PR #321. `test_flow_and_python_strategies_share_semantic_result_contract` compares both strategies through `StrategyRuntime`. | Complete |
| Same downstream offline execution semantics | F4.5.4 PR #324; `test_flow_paper_rehearsal_uses_deployment_preparation_risk_policy_and_paper` plus fail-closed and BACKTEST integration cases exercise deployment binding, preparation, risk/policy, PAPER and deterministic BACKTEST. Issue #322 closed. | Complete |

The implementation and local validation evidence remain bound to the exact candidate SHAs and are recorded in the corresponding PRs. Those results are owner-reported local evidence, not hosted CI. F4.5.4 did not use broker I/O, a sandbox, production or LIVE execution.

### Scope disposition — not M4 exit blockers

The following remain later/deferred platform work and are not part of the single documented M4 exit criterion: visual Flow editor/UI and workflow persistence, external scheduling, webhooks/external signals, streaming, AI nodes/agents, cloud workers, international/crypto markets, direct broker/order nodes and LIVE strategy execution. The curated public Python API (#199) is a separate adoption/stability workstream. Do not create F4.5.5 or broaden Flow v1 without a separately approved requirement and acceptance boundary.

### Remaining work and next priority

- **#267 and #266 remain blocked.** #267 requires a credible alternative authoritative risk-evidence provider/source; keep the pre-collection/no-reservation/no-submit boundary. #266 remains blocked on the missing 0/7 required fixtures; preserve realized-only `daily_pnl`, current `max_drawdown` and the documented session-equity contract.
- **Immediate gate (2026-11-09): PR #329 exact-SHA validation and disposition.** The current draft HEAD is `ce0f19ed046fb99e9bb45e248eda7ee6dad66367` on base `a620b3b13f2cd10c9fee19f61e3afd3121f345ff`. Re-run the canonical default and Dhan-extra validation producers plus both release gates at that exact HEAD; passing evidence at parent `58f3edffb5c46297837cfc99d8d19bf56a43ec0a` does not transfer. Keep the PR draft/unmerged until exact-SHA evidence and the applicable review gates pass. Track T21 separately as an outstanding #200 acceptance item; it is not silently satisfied by this contract-only slice.
- **Next programme priority after that bounded slice: #202, Wave C2 — dead-module and Dhan transport audit.** Start read-only at the then-current main SHA: remeasure import/call-site reachability and current line/branch coverage; determine whether suspected modules are deliberate extension seams or dead code; establish deterministic Dhan transport coverage. Do not remove or wire modules, change adapter behavior, or assume the issue's originally reported percentages before measuring.
- **#200 remains OPEN** after PR #329 unless and until its broader acceptance criteria are satisfied: authoritative effective-dated tariff sources, golden published-rate examples, and the remaining data/behavior gates. Do not populate guessed production rates.
- **#199** remains open; PR #306 is still a draft based on an older main SHA (`ecbb202b8864688b521b1836f5dd9b36ca1d929f`) and has no exact-current-head validation. Reconcile it against current main before any promotion.
- **#190** remains open until a real private disclosure path is configured/verified; resolve before broad public contributor recruitment. Sequence #206 after #199's public API/stability policy.
- **#203** remains conditional on safe broker sandbox access. **#205** remains deferred until reliable Python 3.13 validation infrastructure exists.

No CI, Actions, broker, sandbox, production or LIVE operation is part of this documentation reconciliation.
