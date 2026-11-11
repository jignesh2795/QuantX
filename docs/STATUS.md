# QuantX Status

> **Snapshot:** 2026-11-11. Repository state checked against `main` at `4f4646c55751bf1c6c8208bde1ede9b8336772c7` (PR #328 module-disposition merge). This is a status reconciliation; exact-candidate local validation is recorded separately below.

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
- **QX-12 / Issue #200 India charges:** [PR #329](https://github.com/jignesh2795/QuantX/pull/329) remains open at candidate `5ba5d0a9655c42af2df3fd85e95c126d2c4cfd6b`; issue #200 remains open. The implemented slice is contract-only. P13 Item 21 and the SEBI 15-Oct-2026 circular are recorded in operator-supplied local research evidence. The latest retrieval report says P15 `NCL/CMPT/77212`, predecessors `73370` / `76951`, and BSE `20261030-51` attachments remain **UNVERIFIED/BLOCKED** because no rendered browser/DevTools attachment capture was obtained. Do not claim those documents were retrieved, populate production tariff defaults, or wire physical-settlement calculations.
- **QX-11 / Issue #199 public API:** [PR #331](https://github.com/jignesh2795/QuantX/pull/331) remains open at candidate `71372da3845740e3a134d3735fbf1e4280f3c45f`, based on the pre-PR330 main. The operator report records default/Dhan validation PASS for that exact candidate. This is a separately tracked, optional public API adoption/stability workstream, not a prerequisite for the completed presentation plan or the completed #202 workstream. Revalidate against current main before any merge.
- **Issue #190 security reporting:** closed. On 2026-11-10, the repository owner confirmed GitHub Private Vulnerability Reporting was enabled, the **Report a vulnerability** entry was visible to non-admin reporters, and notification preferences were checked. These are owner-confirmed UI observations; private-reporting API read-back was not independently verified. `SECURITY.md` does not promise an SLA.
- **Issues #266 and #267:** remain blocked on missing source evidence. #266 lacks a coherent set of required Dhan fixtures; #267 lacks an authoritative source for all required LIVE risk fields.
- **Issue #206:** defer conformance-suite/schema work until the public API stability boundary is settled; avoid duplicating provider contracts.

## Validation and evidence

- Validation results are candidate-specific. PR #309 counts belong to its exact validated feature candidate, not a separate full-suite run of its squash merge commit.
- PR #330's reported validation applies to candidate `5cfc0999f4dbd214832facf7753c37595568979f`, not a fresh full-suite run of the squash merge commit `a4b955b1c64c973dc97bd17cf5bbf10578001fc1`.
- PR #328 current-head local validation is operator-reported at candidate `888f4b1ad5841b54f8f09b872c2d70a31558ed00` against base `a4b955b1c64c973dc97bd17cf5bbf10578001fc1`: default 3,621 passed / 3 skipped / 1 warning; Dhan-extra 3,624 passed / 0 skipped / 1 warning; both release gates 10/10 PASS. Dhan transport baseline/final line coverage was 76.06% / 88.08%; branch coverage 67.27% / 78.64%. The merge commit itself was not separately full-suite tested.
- PR #331 validation remains bound to its older base; revalidate against current main before merge.
- GitHub Actions/paid CI is not part of the current project validation workflow. Local validation evidence must identify the exact commit, commands, configuration, counts, and skipped checks.

## Project guardrails

- No additional market implementation is implied by the market-neutral architecture.
- No FX or multi-currency behavior is implied.
- LIVE remains India-only and blocked; no real broker orders or production operations are part of development or validation.
- Keep Decimal-only financial arithmetic, deterministic behavior, explicit provenance, and fail-closed `UNKNOWN` semantics.
- Prefer the smallest implementation that satisfies a current acceptance criterion. Add capability abstractions only when a real implemented behavior and caller require them.

## Historical record

The detailed historical ledger, milestone notes, issue histories, and exact-SHA validation records are preserved in [STATUS_HISTORY.md](STATUS_HISTORY.md). Use this file for historical evidence; do not treat archived checkpoints as current policy.
