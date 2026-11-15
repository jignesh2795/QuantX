# QuantX Status

> **Snapshot:** 2026-11-11. Repository state checked against `main` at `37b6bc8e511ff67b46b42ff00d8cc725d79a0404` (PR #332 documentation reconciliation merge). This is a status reconciliation; exact-candidate local validation is recorded separately below.

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
- **QX-12 / Issue #200 India charges:** [PR #334](https://github.com/jignesh2795/QuantX/pull/334) is the current-main draft, based on `37b6bc8e511ff67b46b42ff00d8cc725d79a0404`. Scope is limited to the vendor-neutral per-trade charge contract and caller-configured, source-versioned NSE India schedules for cash-equity delivery, intraday, futures and options; no production tariff defaults, broker-specific billing assumptions or execution wiring are included. The physical-settlement calculator, State/UT resolver and clearing-specific tests are excluded from this candidate and retained only as deferred research in `docs/planning/india-market-charges-design.md`. P13/P15/BSE source acquisition and inspection remain operator-reported, not independently authenticated. Exact-head validation is required for the revised candidate. Production activation still requires confirmed effective-date/legal interpretation, authoritative rate schedules, explicit client-incidence/GST policy and ordinary-trade worked examples. Physical-delivery STT, F&O delivery stamp duty, State/UT resolution, FOPHY clearing joins and settlement-price/correction workflows are deferred and do not block this issue's per-trade contract milestone. Issue #200 remains open.
- **QX-11 / Issue #199 public API:** [PR #333](https://github.com/jignesh2795/QuantX/pull/333) is the current-main draft at head `bc7f218e1279da028a1978c17fb3aa265c2318f0` based on `37b6bc8e511ff67b46b42ff00d8cc725d79a0404`. The earlier PR #331 was closed as superseded without merge. PR #333 remains draft; its validation report is operator-reported, not hosted CI or independent local reproduction.
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
