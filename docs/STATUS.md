# QuantX Status

> **Snapshot:** 2026-11-15. Repository state checked against main at 37b6bc8e511ff67b46b42ff00d8cc725d79a0404 (PR #332 documentation reconciliation merge). Open candidate PRs are recorded separately; exact-candidate validation remains SHA-bound and operator-reported where stated.

## Product and architecture

QuantX is a local-first, modular Python trading library with a vendor-neutral, market-neutral core and an India-first implementation.

- The canonical market package is `quantx.markets`; the India implementation is `quantx.markets.india`.
- India is the **only fully implemented market**. Digital assets is an interface-only placeholder; other regions are future work.
- No multi-currency or FX conversion is implemented.
- Research, backtest, and paper select market behavior through explicit `MarketContext`.
- Broker SDKs remain behind plugin/adapter boundaries; the Dhan SDK import boundary is `src/quantx/plugins/dhan/transport.py`.
- LIVE execution remains India-only and public LIVE dispatch remains blocked by missing authoritative risk evidence. Passing local tests or paper examples does not establish LIVE readiness.

The market-module migration is complete through PR #309. The legacy `quantx.india` package remains a deprecated compatibility shim; it is not the canonical implementation path. The market capability contract stays minimal and demand-driven; no empty marker protocols are reserved for speculative future markets.

## Milestones

- **v0.1 local-first library scope:** acceptance-complete under ADR-008. The production CLI remains deferred.
- **M4 Strategy Platform:** complete against its documented Python/Flow runtime-parity exit criterion. Visual Flow editing, workflow persistence, scheduling, external signals, streaming, AI/agents, cloud execution, and cross-market strategy execution remain deferred.
- **Market migration and project presentation plans:** the three supplied planning documents have been reconciled. The migration shipped in PR #309; the project presentation/onboarding plan shipped in PR #330.

## Current delivery focus

- **Wave C2 / Issue #202 — completed:** Dhan transport coverage merged in PR #327; measured exact-base-to-final transport coverage improved from 535/678 lines (76.06%) / 148/220 branches (67.27%) at `ce1f179a0f2f2aabb66d273c51bc49a005cd94ff` to 618/678 lines (88.08%) / 173/220 branches (78.64%) at final candidate `888f4b1ad5841b54f8f09b872c2d70a31558ed00`. PR #328 removed the unreferenced `research_policy.py`, updated the skill map/manifest, documented `execution.ports` as canonical, and retained `market_ports.py` as a compatibility-only re-export. PR #328 merged on 2026-11-11 as `4f4646c55751bf1c6c8208bde1ede9b8336772c7`; Issue #202 is closed. Exact-head default and Dhan-extra local validation and release gates passed per the operator report (details below).
- **Project presentation and onboarding:** complete through [PR #330](https://github.com/jignesh2795/QuantX), squash merge `a4b955b1c64c973dc97bd17cf5bbf10578001fc1`, from locally validated candidate `5cfc0999f4dbd214832facf7753c37595568979f`. The exact-candidate operator report recorded default and Dhan-extra canonical validation and release gates PASS (3,621 passed / 3 skipped in each configuration); Ruff was a vacuous pass because no Python files changed. No Actions run is claimed.
- **QX-12 / Issue #200 India charges:** Issue #200 remains OPEN. [PR #329](https://github.com/jignesh2795/QuantX/pull/329) was closed without merge on 2026-11-11; its candidate 5ba5d0a9655c42af2df3fd85e95c126d2c4cfd6b is not in main. The current-main candidate is [Draft PR #334](https://github.com/jignesh2795/QuantX/pull/334), HEAD acfc956eb0ef592327634a7ded52255bd86fec2a based on current main 37b6bc8..., 3 commits ahead / 0 behind. It is scoped to per-trade India charge contracts and excludes physical-settlement calculators and clearing workflows. Its exact-head default/Dhan-extra validation is operator-reported PASS, not independently reproduced here. Issue #200 now records operator-reported official-source retrieval and UDiFF schema findings; unresolved legal/effective-date, ordinary-trade worked-example, client-incidence/GST, FOPHY field-lineage and matched clearing-record questions remain. Do not activate production tariffs or infer physical-delivery calculations.
- **QX-11 / Issue #199 public API:** Issue #199 remains OPEN. [PR #331](https://github.com/jignesh2795/QuantX/pull/331) was closed without merge as superseded. The current-main candidate is [PR #333](https://github.com/jignesh2795/QuantX/pull/333), HEAD bc7f218e1279da028a1978c17fb3aa265c2318f0 based on 37b6bc8...; it is open and not merged. Its default/Dhan-extra validation is operator-reported in the issue history, not independently reproduced here. This remains a separate adoption/stability workstream.
- **Global Digital Assets S1 / ADR-013:** [PR #337](https://github.com/jignesh2795/QuantX/pull/337) remains open as Draft on `feat/qtqx-s1-global-digital-assets-pack-v1`, current head `d18e47153408cd3f3b699cfcd56b75888048d84d`, based on GitHub main `37b6bc8e511ff67b46b42ff00d8cc725d79a0404` (15 commits ahead / 0 behind; 29 changed paths). It adds only synthetic BTC/USDT and ETH/USDT spot fixtures, a 24x7 calendar contract, rule-identity validation and optional TIF semantics; it does not deliver exchange connectivity, accounts, production market rules or crypto trading. The earlier operator-reported PASS applies only to `dd7f4a1...`. The exact-head report for `22876f6454e390392485841871629be30c6e1b15` reported all tests and coverage passing (default 3,662 passed / 3 skipped; Dhan-extra 3,665 passed / 0 skipped), but both producers failed on one changed-file Ruff I001 import-order finding in `digital_assets/__init__.py`. The reported Ruff expectation is `ETH_USDT_SPOT_RULE` before `DigitalAssetSpotRule`, with one fewer blank line before `__all__`. Commit `d18e471...` makes that exact ordering/spacing correction; this newest head is not yet validated. Main continues to treat digital assets as unimplemented until a validated candidate is accepted and merged.
- **Issue #190 security reporting:** closed. On 2026-11-10, the repository owner confirmed GitHub Private Vulnerability Reporting was enabled, the **Report a vulnerability** entry was visible to non-admin reporters, and notification preferences were checked. These are owner-confirmed UI observations; private-reporting API read-back was not independently verified. `SECURITY.md` does not promise an SLA.
- **Issues #266 and #267:** remain blocked on missing source evidence. #266 lacks a coherent set of required Dhan fixtures; #267 lacks an authoritative source for all required LIVE risk fields.
- **Documentation reconciliation:** [Documentation and branch reconciliation (2026-11-15)](planning/documentation-reconciliation-2026-11-15.md) records main-branch coverage, branch-only proposals and exact current PR/issue dispositions. Proposal branches remain unapproved unless separately accepted.
- **Issue #206:** defer conformance-suite/schema work until the public API stability boundary is settled; avoid duplicating provider contracts.

## Validation and evidence

- Validation results are candidate-specific. PR #309 counts belong to its exact validated feature candidate, not a separate full-suite run of its squash merge commit.
- PR #330's reported validation applies to candidate `5cfc0999f4dbd214832facf7753c37595568979f`, not a fresh full-suite run of the squash merge commit `a4b955b1c64c973dc97bd17cf5bbf10578001fc1`.
- PR #328 current-head local validation is operator-reported at candidate `888f4b1ad5841b54f8f09b872c2d70a31558ed00` against base `a4b955b1c64c973dc97bd17cf5bbf10578001fc1`: default 3,621 passed / 3 skipped / 1 warning; Dhan-extra 3,624 passed / 0 skipped / 1 warning; both release gates 10/10 PASS. Dhan transport baseline/final line coverage was 76.06% / 88.08%; branch coverage 67.27% / 78.64%. The merge commit itself was not separately full-suite tested.
- PR #337's operator-supplied exact-head report for `22876f6454e390392485841871629be30c6e1b15` against base `37b6bc8e511ff67b46b42ff00d8cc725d79a0404` is FAIL only because changed-file Ruff reports one I001 import-order finding in `src/quantx/markets/digital_assets/__init__.py`. The focused suite passed 179/179; default full suite passed 3,662 with 3 skips; Dhan-extra passed 3,665 with no skips; package coverage floors, Ruff format, mypy (0 errors across 238 files), diff check and worktree integrity were reported PASS. Both release reports remain FAIL because the validation producer failed on Ruff. The reported measurements were domain 88.85% line / 75.09% branch, execution 89.30% / 75.45%, persistence 93.16% / 81.48%. Commit `d18e471...` changes the Ruff import ordering and removes the extra blank line before `__all__`; no validation is yet available for that head. Operator-local JSON evidence was not independently accessed or authenticated here.
- PR #329 and PR #331 were closed without merge; their candidate validation must not be treated as main-branch evidence. PR #333 and PR #334 are separate current-main candidates and remain unmerged. Their supplied local validation reports are operator-reported and tied to their exact heads.
- GitHub Actions/paid CI is not part of the current project validation workflow. Local validation evidence must identify the exact commit, commands, configuration, counts, and skipped checks.

## Project guardrails

- No additional market implementation is implied by the market-neutral architecture.
- No FX or multi-currency behavior is implied.
- LIVE remains India-only and blocked; no real broker orders or production operations are part of development or validation.
- Keep Decimal-only financial arithmetic, deterministic behavior, explicit provenance, and fail-closed `UNKNOWN` semantics.
- Prefer the smallest implementation that satisfies a current acceptance criterion. Add capability abstractions only when a real implemented behavior and caller require them.

## Historical record

The detailed historical ledger, milestone notes, issue histories, and exact-SHA validation records are preserved in [STATUS_HISTORY.md](STATUS_HISTORY.md). Use this file for historical evidence; do not treat archived checkpoints as current policy.
