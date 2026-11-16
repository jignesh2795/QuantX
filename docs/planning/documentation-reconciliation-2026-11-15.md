# QuantX Documentation and Branch Reconciliation

**Original audit date:** 2026-11-15
**Follow-up state/scope reconciliation:** 2026-11-16
**Repository:** [jignesh2795/QuantX](https://github.com/jignesh2795/QuantX)
**Audited main HEAD:** 37b6bc8e511ff67b46b42ff00d8cc725d79a0404
**Audit branch:** docs/reconcile-quantx-documentation-2026-11-15
**Mode:** GitHub-side inspection followed by a documentation-only reconciliation on this branch; this 2026-11-16 follow-up corrects PR states and the subsequent #200 scope decision.

## 1. Executive disposition

QuantX already has a substantial documentation system on main. The documentation gap is not that all previous work is missing. It is that some proposals remain on separate branches and the canonical status / roadmap pages contain stale PR state and stale evidence-acquisition wording.

The safe disposition is:

1. Keep the existing canonical architecture, implementation, roadmap, status, research and governance documents; do not recreate them.
2. Correct the stale PR #329 / #331 and India-charges evidence statements using current GitHub state.
3. Record the global-market, crypto and scope-restoration proposals as unapproved references, not accepted architecture or active implementation.
4. Keep PR #333 as the current-main public API review candidate; keep PR #334 Draft/parked and do not merge its broader India statutory model wholesale.
5. Keep PR #337 Draft/deferred as a synthetic Digital Assets proposal; it is not accepted scope or shipped market support.
6. For #200, follow the 2026-11-12 decision: implement only a caller-supplied per-fill cost schedule through the existing charge/receipt/accounting path. No production tariffs, daily STT aggregation, clearing, physical settlement or LIVE wiring.

This reconciliation changes documentation on the audit branch only. It does not change implementation code, issues, existing PRs or main.

## 2. Repository evidence and audit scope

The current default branch is main at 37b6bc8e511ff67b46b42ff00d8cc725d79a0404.

GitHub branch enumeration returned **165 branch refs**, including **46 branches with a docs/ prefix**. The recursive main tree was complete and not truncated (703 tree entries). Within the selected documentation/governance scope—docs/, root README.md, VISION.md, AGENTS.md, OpenCode skill definitions and their lock manifest—122 files were present. The .opencode/skills/ tree contains 19 SKILL.md definitions on main.

The audit inspected:
- Repository metadata, current main ref and recursive tree.
- Branch refs and exact branch HEAD SHAs.
- Branch-to-main comparisons for material documentation and current issue branches.
- Current PR metadata and current Issue #199 / #200 records.
- Canonical files including docs/README.md, docs/STATUS.md, docs/STATUS_HISTORY.md, docs/architecture/README.md, docs/architecture/32-global-market-separation.md, docs/decisions/README.md, docs/roadmap/README.md, docs/planning/quantx-work-program-2026-10.md, README.md, VISION.md and AGENTS.md.

This is a GitHub-side audit. It cannot establish local unpushed worktrees, stashes or uncommitted files on the operator's machine. It did not run local pytest, Ruff, mypy or release gates, and it did not invoke GitHub Actions.

## 3. Documentation already present on main

The following are present and should be maintained rather than regenerated:

| Area | Canonical location / evidence |
|---|---|
| Product identity and scope | README.md, VISION.md |
| Project instructions and agent policy | AGENTS.md, .opencode/skills/, .opencode/skills/skills.lock.json |
| Current status and historical evidence | docs/STATUS.md, docs/STATUS_HISTORY.md |
| Architecture principles, package boundaries and market-neutral separation | docs/architecture/README.md, numbered architecture records, docs/architecture/32-global-market-separation.md |
| Accepted ADRs | docs/architecture/adr/ADR-001 through ADR-012 |
| Implementation guidance | docs/implementation/README.md and its referenced records |
| Product sequencing and milestones | docs/roadmap/README.md, docs/planning/quantx-work-program-2026-10.md |
| Comparative trading-engine research | docs/research/2026-11-global-architecture-comparison.md |
| Contributor and community documentation | CONTRIBUTING.md, ARCHITECTURE.md, docs/GETTING_STARTED.md, CODE_OF_CONDUCT.md, SECURITY.md, CHANGELOG.md and related templates |

The pinned comparative review in docs/research/2026-11-global-architecture-comparison.md was merged through [PR #315](https://github.com/jignesh2795/QuantX/pull/315). It is distinct from the separate global product-vision / market-roadmap proposal branch.

Community/onboarding and skill-hardening work is already merged, including [PR #245](https://github.com/jignesh2795/QuantX/pull/245), [PR #330](https://github.com/jignesh2795/QuantX/pull/330) and [PR #332](https://github.com/jignesh2795/QuantX/pull/332). The documentation index already establishes the one-source-of-truth rule.

## 4. Current PR and issue state — reverified 2026-11-16

| Workstream | Current GitHub state | Correct interpretation |
|---|---|---|
| #200 transaction costs | [PR #334](https://github.com/jignesh2795/QuantX/pull/334) remains **open, Draft / parked**, branch integration/issue200-current-main-v1, HEAD `b7f44b72b45e60a5d59b52f8a947d27f67d8550b`, base main at `37b6bc8...`; 7 ahead / 0 behind, 9 paths. Issue #200 remains open. | Its operator-reported exact-head PASS (56 focused tests in both configurations, default 3,671/3 skipped, Dhan 3,674/0, both 10/10 release gates) applies only to this broader India statutory schedule branch. The 2026-11-12 issue decision instead selects a generic caller-supplied per-fill schedule through the existing `ChargeModel` and receipt/accounting path. Preserve #334 as source/reference material; do not merge or reuse wholesale. |
| #199 curated public API | [PR #333](https://github.com/jignesh2795/QuantX/pull/333) is **open, Ready for Review**, branch integration/issue199-current-main-v1, HEAD `bc7f218e1279da028a1978c17fb3aa265c2318f0`, base main at `37b6bc8...`. Issue #199 remains open. | Current-main public API candidate; not merged. The supplied local validation report is operator-reported. It remains separate from the #200 implementation. |
| Earlier #200 candidate | [PR #329](https://github.com/jignesh2795/QuantX/pull/329) is **closed without merge** (closed 2026-11-11), HEAD 5ba5d0a9655c42af2df3fd85e95c126d2c4cfd6b, based on older main a620b3b... | Its code and local validation evidence are branch/PR history, not main-branch functionality. |
| Earlier #199 candidate | [PR #331](https://github.com/jignesh2795/QuantX/pull/331) is **closed without merge** (closed 2026-11-11), HEAD 71372da3845740e3a134d3735fbf1e4280f3c45f, based on older main a620b3b... | Superseded by PR #333; do not describe #331 as open or current. |
| Post-#307 status draft | [PR #308](https://github.com/jignesh2795/QuantX/pull/308) remains **open, Draft**, based on 93ae5d0..., HEAD d72b6826aa3950875805e56bf6fad75d7dea0a1b. | Stale relative to current main. Preserve its historical validation record, but do not use its old snapshot as current policy. |
| Digital Assets S1 proposal | [PR #337](https://github.com/jignesh2795/QuantX/pull/337) remains **open, Draft**, HEAD `d7e4e96548e2423e1b64b75100bb87a099d9bb70`. | Synthetic/registration-compatible only; deferred, unmerged, and not implemented crypto support. |
| Documentation reconciliation | [PR #336](https://github.com/jignesh2795/QuantX/pull/336) remains **open, Draft**, branch `docs/reconcile-quantx-documentation-2026-11-15`. | Documentation-only reconciliation; this follow-up needs exact-head local doc validation before PR #336 can be marked ready. |

### #200 source and scope correction

The previous main-branch status says the P15 / predecessor / BSE attachments were unverified because rendered-browser capture was unavailable. That statement is superseded by newer Issue #200 history and the PR #334 report.

Current issue history reports official-source retrieval and inspection of P13/P15, predecessor circulars, BSE material and UDiFF Annexure B/C. It also records UDiFF schema-discovery findings. These are **operator-reported research findings**; this audit did not obtain the operator's local binary files or independently reproduce their hashes and page-by-page inspection.

The later #200 scope decision is narrower than the statutory/clearing research register. The accepted implementation direction is a modelled caller-configured per-fill schedule: named side-aware lines, turnover/units/order/dependent-charge bases, explicit currency precision, final fill-total rounding once, deterministic identity and provenance, applied through the existing receipt/cash/net-P&L path. The FOPHY/Rule 3/physical-settlement and clearing research remains preserved but is outside this implementation. No exchange-final STT or broker tariff is claimed.

**Evidence qualification:** PR #334's exact-head validation at `b7f44b72b45e60a5d59b52f8a947d27f67d8550b` remains operator-reported PASS in both locked configurations and release gates; it was not rerun here and does not establish acceptance of the selected per-fill schedule. Issue #200 remains OPEN; PR #334 is Draft/parked and unmerged.

## 5. Material branch-only documentation and proposals

The following branch contents were verified on GitHub. A branch name or committed proposal does not mean the proposal was approved.

| Branch | HEAD | Comparison to main | Content / disposition |
|---|---|---:|---|
| docs/global-architecture-proposal-2026-10 | 34a04d3656812cfd3071e74f8b0d6d970daf7a6f | 6 ahead / 235 behind; diverged | Adds docs/proposals/global-product-vision.md, comparative-architecture-audit.md, global-market-support-roadmap.md. Proposal/planning material, not approved or merged. |
| docs/crypto-market-extension-plan | 2b9e22440537d57dc98141f797d3980a74bf7851 | 3 ahead / 235 behind; diverged | Adds docs/planning/crypto-market-extension-plan.md and docs/roadmap/digital-assets-market-expansion.md; adjusts global-market and roadmap indexes. Planning proposal only. |
| docs/quantx-scope-restoration-audit-v1 | 350b55dba172af69b3e08b585d89b2d19a3ab2e5 | 1 ahead / 0 behind | Adds docs/planning/quantx-product-scope-and-delivery-roadmap.md. Proposes an India-first product scope with a global-neutral architecture; not merged or formally adopted. |
| docs/global-market-plan-reconciliation-2026-11-09 | f60a8cc249b20cc4fe1c25695da09dab48379a7f | 2 ahead / 14 behind; diverged | Reconciles older STATUS, global-market and work-programme wording. Older-base reconciliation branch, not a current-main update. |
| [PR #337](https://github.com/jignesh2795/QuantX/pull/337) / `feat/qtqx-s1-global-digital-assets-pack-v1` | `d7e4e96548e2423e1b64b75100bb87a099d9bb70` | 16 ahead / 0 behind; open, Draft / deferred | Adds ADR-013 and synthetic BTC/USDT + ETH/USDT Digital Assets fixtures, optional-TIF semantics and rule/calendar guards. It has no exchange connectivity, account, broker transport, production rule authority or crypto trading capability. Earlier validation is operator-reported and branch-specific. The proposal remains unmerged and is not accepted implementation scope. |

### Issue-specific branch caution

Issue #200 has several additional implementation branches. The most relevant are:

- integration/issue200-current-main-v1 — preserved as Draft/parked PR #334 at `b7f44b72b45e60a5d59b52f8a947d27f67d8550b`; it is not the selected next implementation.
- fix/issue200-state-ut-validation-v1 at 63254cfe879d13a0c196b0aac05f1dd6cdf15fe2 — 2 commits ahead of current main, unsubmitted; includes physical-settlement-related files.
- fix/issue200-physical-settlement-format-v1 at 5fcb69920a25050e4eb5e7d72991af7fdf5f4867 — 32 ahead / 14 behind; diverged from main.
- feat/issue200-india-charge-contract-v1 at 5ba5d0a9655c42af2df3fd85e95c126d2c4cfd6b — closed PR #329 candidate, 34 ahead / 14 behind.

Other November 2–3 integration branches are divergent from current main. Preserve them as evidence/salvage sources only; do not merge or cherry-pick them wholesale. PR #334 remains parked; the #200 per-fill schedule must be developed through the canonical charge seam, not by reviving the statutory candidate wholesale.

## 6. Reconciliation changes on this branch

The canonical status and roadmap pages are corrected so they no longer say PR #329 or PR #331 remains open. The updated records distinguish:

- PR #329: closed without merge; candidate remains unmerged.
- PR #334: current-main statutory India charge candidate, Draft/parked at `b7f44b72b45e60a5d59b52f8a947d27f67d8550b`; its exact-head validation PASS is operator-reported but does not represent the selected per-fill scope.
- PR #331: closed without merge and superseded.
- PR #333: current-main public API candidate, open and not merged.

The stale statement that P15 and companion source attachments were unavailable is replaced with the newer, carefully qualified Issue #200 history: retrieval and schema findings are operator-reported. Those findings remain research provenance, not a reason to keep the broader statutory charge candidate as the active implementation.

The global product vision, crypto roadmap and scope-restoration audit remain proposal-only references. ADR-013 and the synthetic Digital Assets pack remain in open Draft PR #337; they are not merged or accepted on main. The PR does not establish venue connectivity or crypto trading support.

## 7. Recommended disposition

1. Keep main's existing identity: market-neutral core, India-first implementation, India as the only fully implemented market, and digital assets as a placeholder.
2. Review the scope-restoration proposal against current product intent before adopting it. Its India-first direction is consistent with current README/VISION wording, but adoption should be explicit.
3. Keep the global-architecture and crypto plans as unapproved planning references until a specific product decision authorizes a bounded next market.
4. Keep PR #334 Draft/parked. Implement #200's caller-supplied per-fill schedule through the existing canonical charge pipeline; keep the separate physical-settlement branch family deferred.
5. Review PR #333 against its public API acceptance criteria. PR #331 is historical/superseded.
6. Keep S1 / ADR-013 and PR #337 Draft/deferred; its prior validation and source review do not promote the synthetic market pack into current India-first scope. Preserve the non-claims and do not broaden LIVE eligibility.
7. Continue to use one canonical current status and one cross-workstream work programme; retain older snapshots as history rather than current policy.

## 8. Audit limitations and non-claims

- Local unpushed worktrees, stashes, uncommitted files and operator-local evidence directories were not accessible to this GitHub-side audit.
- Operator-reported test results and research attachment inspections were not rerun or cryptographically authenticated here.
- The earlier local documentation validation report applies to the pre-follow-up head `a71885f087d29639460ba94cf1110e73d4ab7843` only. This new documentation head requires fresh local `git diff --check`, link/Markdown/encoding and exact-SHA validation.
- No GitHub Actions, paid CI, broker, exchange, sandbox, production or LIVE operation was performed.
- No source code, issue state, release or repository setting was changed by this documentation follow-up. PR-state changes for #334, #336 and #337 were performed separately and read back; this commit only updates the existing documentation reconciliation branch.

**Follow-up takeaway (2026-11-16):** the documentation inventory remains valid, but PR #334 and #337 are deliberately parked as Drafts. Issue #200's next implementation is the generic per-fill cost schedule already scoped in its history; do not expand into a statutory/clearing subsystem or create another parallel charge ledger.
