# QuantX Master Work Programme — October/November 2026

**Status:** Active cross-workstream sequencing and reconciliation record

**Snapshot date:** 2026-11-11

**Baseline reviewed for this reconciliation:** `main` at `4f4646c55751bf1c6c8208bde1ede9b8336772c7` (PR #328 module-disposition merge).

**Purpose:** Keep prior architecture, safety, India-market realism, global-market research, strategy/research delivery, and release-readiness work in one progressable plan.

This is the canonical **active sequencing** document. GitHub issues remain the canonical individual acceptance/checklist records; `docs/STATUS.md` remains the current implementation/evidence ledger; `docs/roadmap/README.md` remains the capability and milestone history. When an older status snapshot or planning note conflicts with the current issue acceptance criteria or this priority order, reconcile it before implementing. Do not infer completion from a branch name, documentation, or an old test count.

## 1. Repository snapshot and governance

- Latest `main` baseline used for this programme update: `4f4646c55751bf1c6c8208bde1ede9b8336772c7`.
- PR #309 market-module migration is merged; PR #330 completed the project-presentation/onboarding plan at `a4b955b1c64c973dc97bd17cf5bbf10578001fc1` from locally validated candidate `5cfc0999f4dbd214832facf7753c37595568979f`.
- **Wave C2 / Issue #202 is complete.** PR #327 merged at `a620b3b13f2cd10c9fee19f61e3afd3121f345ff`; PR #328 merged at `4f4646c55751bf1c6c8208bde1ede9b8336772c7` from validated current-base candidate `888f4b1ad5841b54f8f09b872c2d70a31558ed00`. Measured Dhan transport coverage improved from baseline 535/678 lines (76.06%) and 148/220 branches (67.27%) to final 618/678 lines (88.08%) and 173/220 branches (78.64%). The #202 85% line threshold is met; branch coverage is separately reported with no branch threshold specified. The module-disposition changes remove the unused research policy scaffold and retain the execution market-port compatibility shim with an explicit deprecation/removal condition. Issue #202 closed as completed after exact-head default/Dhan validation and release-gate evidence.
- PR #295 is closed as superseded by #309. PR #306 is closed/superseded by the current public API candidate. PR #308 remains a stale documentation draft; do not reintroduce its snapshot as current policy.
- PR #329 (#200) remains open with a contract-only slice; its market-rule research has unresolved primary-source acquisition/interpretation gaps. PR #331 (#199) remains open with a corrected provisional API candidate and exact-candidate local validation, but is a separate adoption/stability workstream and is not the next task.
- PR #330 preserves the detailed status history in `docs/STATUS_HISTORY.md`; #190 is closed after owner-confirmed Private Vulnerability Reporting UI setup. The Code of Conduct continues to disclose that no dedicated confidential conduct contact route has been published.
- The parent M4 exit criterion is met; M4.5.1–M4.5.4 and issue #322 are complete. The market-module migration and presentation plan are complete within their approved scope.

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
| Completed | [#202 dead-module and Dhan transport coverage audit](https://github.com/jignesh2795/QuantX/issues/202) | PR #327 and PR #328 are merged; baseline/final Dhan line and branch coverage is recorded above; the line threshold is met; module removal/compatibility retention decisions are documented; issue closed 2026-11-11. |

### Wave D — India-market realism and public contract

| Rank | Issue | Next required outcome |
|---|---|---|
| D1 | [#200 effective-dated India charges schedule](https://github.com/jignesh2795/QuantX/issues/200) | The contract-only PR #329 is open. Retain the current charge contract and synthetic fixtures; no production tariff activation or paper-execution wiring. P13 Item 21 and the SEBI 15-Oct-2026 circular are recorded in operator-supplied local research. The latest operator report marks P15 `NCL/CMPT/77212`, predecessors `73370` / `76951`, and BSE `20261030-51` attachments UNVERIFIED/BLOCKED because rendered-browser/DevTools capture was not obtained. Resolve legal/clearing uncertainties before production rules. |
| Completed | [#201 finite Decimal-only Money](https://github.com/jignesh2795/QuantX/issues/201) | PR #310; validated candidate `24e3a3bc6205c6d8d5f7733d63c79a2ce94b0617`; squash merge `a2007f6a04859368608a42cd3898244382151a5a`. |
| D3 — deferred | [#199 curated provisional public API](https://github.com/jignesh2795/QuantX/issues/199) | PR #331 contains the provisional `quantx.api` candidate at `71372da3845740e3a134d3735fbf1e4280f3c45f`. It has an operator-reported exact-candidate default/Dhan validation PASS against the prior base, but main advanced in PR #330. Revalidate against current main before any merge. Keep this separate from the immediate #202 work. |

The charges contract/design is available in `docs/planning/india-market-charges-design.md`; source and unresolved rule evidence are recorded in `docs/planning/risk-charges-evidence-reconciliation.md`. These documents are design/research inputs only. Do not treat a synthetic fixture, secondary transcription, or rate label as proof of regulatory authority.

### Wave E — Integration proof, ecosystem and public readiness

| Rank | Issue / workstream | Next required outcome |
|---|---|---|
| E1 | [#203 Dhan sandbox lifecycle evidence](https://github.com/jignesh2795/QuantX/issues/203) | Only when safe non-production sandbox access is available; produce replayable evidence fixtures and preserve a strict no-real-capital boundary. |
| E2 | [#206 broker/market-data conformance and schemas](https://github.com/jignesh2795/QuantX/issues/206) | Defer until #199's public API/stability boundary is settled; then add only the contract suites/schema surfaces justified by actual consumers. Do not duplicate provider definitions. |
| Completed | [#188 StrategySignal confidence contract](https://github.com/jignesh2795/QuantX/issues/188) | Confidence remains a bounded strategy score, not a calibrated probability absent calibration evidence. Issue closed. |
| Completed | [#190 security reporting policy](https://github.com/jignesh2795/QuantX/issues/190) | Closed after owner-confirmed GitHub Private Vulnerability Reporting UI availability and notification-setting checks. API read-back was not independently verified; no SLA/bounty is promised. |
| Completed | Project presentation/onboarding plan — [PR #330](https://github.com/jignesh2795/QuantX/pull/330) | Squash-merged at `a4b955b1c64c973dc97bd17cf5bbf10578001fc1` from validated candidate `5cfc0999f4dbd214832facf7753c37595568979f`. README, getting-started guide, community files, package metadata, documentation navigation and status-history split are delivered within plan scope. The Code of Conduct explicitly discloses that no dedicated confidential conduct contact route is published. |
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

The approved presentation/onboarding plan is **complete** through [PR #330](https://github.com/jignesh2795/QuantX), squash-merged at `a4b955b1c64c973dc97bd17cf5bbf10578001fc1`. Its exact candidate `5cfc0999f4dbd214832facf7753c37595568979f` passed the operator-supplied default and Dhan-extra canonical validation and release gates. This completes that plan; it does not mean every later public-adoption task is complete.

| Area | Current state | Remaining action |
|---|---|---|
| Market-module migration | **Complete** — PR #309 merged; India is the only implemented market, digital assets remains a placeholder. | Do not redo or broaden without a new requirement. |
| Human contributor and architecture entry | **Completed** — #187/#204 closed; `CONTRIBUTING.md`, `ARCHITECTURE.md`, `docs/GETTING_STARTED.md` and offline paper example exist. | Maintain commands/links against actual code. |
| Community files, README and package metadata | **Completed within PR #330** — Code of Conduct, Security Policy, Changelog, CODEOWNERS, issue/PR templates, package URLs/metadata and navigation are present. | Do not invent personal author email or a dedicated confidential conduct contact route; the current documents disclose those limitations. |
| Status history/navigation | **Completed within PR #330** — concise `docs/STATUS.md` plus preserved `docs/STATUS_HISTORY.md`. | Keep the concise status and this master programme current; do not create a new permanent doc for each batch. |
| Security disclosure | **Completed for #190** — issue closed after owner-confirmed GitHub Private Vulnerability Reporting UI and notification checks. | No response SLA or API verification is claimed. |
| Curated Python API | **Open / separate** — #199; PR #331 contains the current provisional API candidate. | Reconcile and validate against current main before any merge. This is not a blocker for the completed presentation plan. |
| CI presentation | GitHub Actions/paid CI remains unavailable by project policy. | No CI badge or green-CI claim. Continue exact-SHA local validation. |

Issue #206 conformance tests and versioned schemas remain sequenced after #199's stability policy. #203 remains conditional on safe non-production sandbox access; #205 remains deferred until reliable Python 3.13 validation is available.

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
- **Wave C2 / #202 is complete** in PRs #327/#328; preserve the measured baseline/final line and branch coverage and the compatibility-shim deprecation decision. Do not reopen or expand into general architecture cleanup without a new issue and evidence.
- **Next actionable work: Wave D / #200 effective-dated India charges**, subject to its primary-source/legal gates. PR #329 is still contract-only; P13/SEBI evidence is operator-supplied, while P15, its predecessors and BSE joint-SOP attachments remain UNVERIFIED/BLOCKED under the latest retrieval report. No production rates or physical-settlement wiring until authoritative sources and interpretation are established.
- **#200** remains the India charges-schedule workstream; PR #329 is contract-only. P13/SEBI local evidence is operator-supplied; P15, its predecessors and the BSE joint SOP are UNVERIFIED/BLOCKED under the latest retrieval report. No guessed production rate or physical-settlement implementation.
- **#199** remains open in PR #331. The earlier draft PR #306 is superseded; do not revive it. Revalidate #331 against current main only if/when this public API work is selected.
- **#190** is closed. The presentation plan is complete; the Code of Conduct's lack of a dedicated confidential contact route remains disclosed rather than fabricated.
- **#203** remains conditional on safe broker sandbox access. **#205** remains deferred until reliable Python 3.13 validation infrastructure exists. Sequence #206 after #199's public API/stability policy.

No GitHub Actions, paid CI, broker, exchange, sandbox, production or LIVE operation is part of this documentation reconciliation.
