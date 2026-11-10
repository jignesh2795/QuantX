# QuantX Status

> **Snapshot:** 2026-11-10. Repository state checked against `main` at `a620b3b13f2cd10c9fee19f61e3afd3121f345ff`. This is a status summary, not a new validation run.

## Product and architecture

QuantX is a local-first, modular Python trading library with a vendor-neutral, market-neutral core and an India-first implementation.

- The canonical market package is `quantx.markets`; the India implementation is `quantx.markets.india`.
- India is the **only fully implemented market**. Digital assets is an interface-only placeholder; other regions are future work.
- No multi-currency or FX conversion is implemented.
- Research, backtest, and paper select market behavior through explicit `MarketContext`.
- Broker SDKs remain behind plugin/adapter boundaries; the Dhan SDK import boundary is `src/quantx/plugins/dhan/transport.py`.
- LIVE execution remains India-only and public LIVE dispatch remains blocked by missing authoritative risk evidence. Passing local tests or paper examples does not establish LIVE readiness.

The PR #309 market-module migration is complete. The legacy `quantx.india` package is a deprecated compatibility shim; it is not the canonical implementation path.

## Milestones

- **v0.1 local-first library scope:** acceptance-complete under ADR-008. The production CLI remains deferred.
- **M4 Strategy Platform:** complete against its documented Python/Flow runtime-parity exit criterion. Visual Flow editing, workflow persistence, scheduling, external signals, streaming, AI/agents, cloud execution, and cross-market strategy execution remain deferred.

## Current delivery focus

- **Project presentation and onboarding:** in progress in draft [PR #330](https://github.com/jignesh2795/QuantX/pull/330). The scope is repository hygiene, community health, README/package identity, documentation navigation, and preserving the detailed status history.
- **QX-12 / Issue #200 India charges:** separate India-specific engineering work. [PR #329](https://github.com/jignesh2795/QuantX/pull/329) is ready for review at candidate `5ba5d0a9655c42af2df3fd85e95c126d2c4cfd6b`; issue #200 remains open. Its contract slice does not supply production tariffs, clearing-report ingestion, final settlement-price selection, physical STT, or execution integration.
- **Issue #190 security reporting:** a truthful `SECURITY.md` policy is included in PR #330. The repository's GitHub Private Vulnerability Reporting setting and notification path are not verified; issue #190 remains open until a maintainer verifies/enables that setting or establishes another monitored private route.
- **Issue #202:** read-only dead-module and Dhan-transport audit remains a separate engineering work item.
- **Issues #266 and #267:** remain blocked on missing source evidence. #266 lacks a coherent set of required Dhan fixtures; #267 lacks an authoritative source for all required LIVE risk fields.
- **Issue #199 public API:** a curated `quantx.api` surface remains separately tracked and deferred; no stable public API module is claimed.

## Validation and evidence

- Validation results are candidate-specific. The PR #309 counts belong to its exact validated feature candidate, not a separate full-suite run of the squash merge commit.
- The latest PR #329 validation is recorded in that PR and applies to its exact candidate SHA, not to `main`.
- This status snapshot does not claim a fresh full-suite, coverage, Ruff, or mypy run at the `main` baseline above.
- GitHub Actions/paid CI is not part of the current project validation workflow. Local validation evidence must identify the exact commit, commands, configuration, counts, and skipped checks.

## Project guardrails

- No additional market implementation is implied by the market-neutral architecture.
- No FX or multi-currency behavior is implied.
- LIVE remains India-only and blocked; no real broker orders or production operations are part of development or validation.
- Keep Decimal-only financial arithmetic, deterministic behavior, explicit provenance, and fail-closed `UNKNOWN` semantics.

## Historical record

The detailed historical status ledger, milestone notes, issue histories, and exact-SHA validation records are preserved in [STATUS_HISTORY.md](STATUS_HISTORY.md). Use this file for current state; do not treat archived checkpoints as current policy.
