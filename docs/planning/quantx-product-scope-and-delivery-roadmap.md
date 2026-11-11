# QuantX Product Scope Restoration Audit and Delivery Roadmap

**Status:** Audit baseline and proposed scope decision; not a release declaration  
**Audit date:** 2026-11-11  
**Repository:** `jignesh2795/QuantX`  
**Audited base:** `main` at `37b6bc8e511ff67b46b42ff00d8cc725d79a0404`  
**Audit branch:** `docs/quantx-scope-restoration-audit-v1`  
**Scope:** Read-only reconciliation of product intent, current implementation/status records, architecture boundaries, and all open issues returned by GitHub at the audit time.

## 1. Executive decision

QuantX should remain an **India-first, local-first, open-source algorithmic trading engine and platform library**, with a market-neutral core and India as the only implemented market.

The repository is not currently a complete end-user trading application or hosted brokerage control plane. It is a Python modular monolith/library with deterministic domain contracts, strategy and research workflows, paper execution, broker/data adapter seams, persistence, and guarded LIVE composition. The product roadmap must describe that actual product honestly rather than imply a finished desktop/web application.

The immediate correction is not to remove sound architecture or safety work. It is to stop treating every future extensibility idea, research tool, or optional adoption feature as a prerequisite to the core product.

**Scope decision proposed by this audit:**
- Keep Indian-market strategy research, backtesting, paper execution, broker integration, portfolio/account state, risk, reconciliation, and operational reliability as the product's central capability set.
- Keep the universal core and plugin boundaries because they reduce market/broker coupling; do not implement additional markets merely because the abstractions permit them.
- Preserve LIVE fail-closed controls as mandatory safety obligations. A platform intended to support algorithmic execution cannot waive risk authority, loss controls, recovery, or reconciliation to achieve a faster demo.
- Defer UI/CLI, AI/ML, autonomous trading agents, cloud/distributed execution, broad broker expansion, crypto/global implementations, and general-purpose agent infrastructure unless separately prioritized by a concrete user need and acceptance criterion.
- Do not combine Universal Brain, coding-agent orchestration, or other independent projects into QuantX's delivery milestones.

This is a scope-restoration decision, not an instruction to delete existing code or rewrite the architecture.

## 2. Evidence examined and provenance

Directly inspected on GitHub:
- Repository metadata and `main` branch ref; current `main` SHA is `37b6bc8e511ff67b46b42ff00d8cc725d79a0404`.
- `README.md`, `docs/STATUS.md`, `docs/roadmap/README.md`.
- `docs/planning/quantx-work-program-2026-10.md` and `docs/planning/research-and-direction.md`.
- Architecture index, overview, India-market domain, v0.1 acceptance criteria, global-market separation, current package map, implementation batch plan, and LIVE safety audit record.
- All eight issues returned by the repository-scoped open-issue search: #199, #200, #203, #205, #206, #207, #266, #267.

Evidence classifications:
- **Directly verified:** repository metadata, branch SHA, file contents, issue states/titles and issue-body contents retrieved during this audit.
- **Operator-reported (retained as such):** test/coverage/release-gate results already recorded in repository documentation. This audit did not rerun local test commands.
- **Derived:** product-scope conclusions and sequencing recommendations based on the inspected records.
- **Unknown:** local worktree state, uncommitted changes on the user's machine, and any facts not exposed by the GitHub reads.

The active work-program and status files still contain earlier baseline references (for example, `4f4646c...`). This audit binds its own inspection to `37b6bc8...`; older validation counts are not promoted to validation of this audit branch or current main.

## 3. What QuantX actually is today

### 3.1 Product identity

The README describes QuantX as open-source, event-driven trading infrastructure with a market-neutral core and an India-first implementation. It is a local-first Python trading library and modular monolith. The India market module is the only fully implemented market. Digital assets is an interface-only placeholder; other regions, multi-currency, and FX conversion are not implemented.

The current product is therefore best described as:

> An extensible Indian-market-first algorithmic trading engine/library for building and evaluating strategies, running deterministic backtests and paper workflows, and integrating supported brokers through explicit adapter contracts, with a safety-first path toward controlled LIVE execution.

Do not describe QuantX as already providing a complete visual trading terminal, hosted service, universal multi-market platform, crypto platform, or unrestricted LIVE-ready system.

### 3.2 Core capabilities already present or explicitly accepted

- Market-neutral domain and execution contracts, with India-specific rules in `quantx.markets.india`.
- Strategy definitions/IR/runtime and the bounded declarative Flow path through the existing strategy runtime.
- Historical research, dataset identity/provenance, deterministic ingestion and persisted research runs/experiments.
- Backtest and paper execution using canonical downstream semantics.
- Broker and market-data plugin boundaries, including Dhan and reference adapters.
- Durable execution receipts, idempotency, lifecycle/reconciliation, startup recovery, and fail-closed trading gates.
- Local-first persistence and documented programmatic host workflow.
- India charges/market-pack contracts, with verified tariff completeness still an open work item.

The v0.1 programmatic local-first library scope is recorded as acceptance-complete. The M4 strategy-platform milestone is recorded complete against its defined exit criterion. Those statements do not mean all later UI, broker, or production LIVE capabilities are complete.

### 3.3 Explicitly not delivered / not implied

- Production LIVE readiness: public LIVE dispatch remains blocked by missing authoritative risk evidence.
- Complete authoritative Dhan account/day risk evidence, including all required account financial state and exposure/P&L inputs.
- A completed Indian tariff schedule for every supported product/segment/date combination.
- A production CLI or visual strategy editor.
- Streaming market data where the adapter explicitly supports snapshot-only behavior.
- Multi-leg execution (design exists; implementation/capability is not claimed).
- Global markets, crypto trading, FX conversion, and cross-market currency aggregation.
- AI/ML model registry, AI strategy generation, autonomous trading agents, hosted/cloud workers, or distributed orchestration.
- A general-purpose project/agent operating system.

## 4. Product boundary: retain, defer, separate

| Area | Decision | Reason / boundary |
|---|---|---|
| India market domain (NSE/BSE and supported Indian segments) | **Core** | First and only implemented market; rules, instruments, sessions, charges and contract semantics are product-specific requirements. |
| Broker/data adapters | **Core seam; incremental integrations** | Required for practical use, but broker count is not the product's primary success metric. Preserve adapter isolation and add only when acceptance and maintenance justify it. |
| Strategy authoring/runtime | **Core** | A strategy engine is central to an algo-trading platform. Reuse the existing Python/Flow runtime; do not create a second runtime. |
| Historical data, backtesting and research integrity | **Core** | Strategy evaluation requires reproducible data, point-in-time rules, realistic costs/fills and provenance. |
| Paper execution | **Core** | Safe operational rehearsal and semantic parity are essential before LIVE. |
| Risk, portfolio/account state, order lifecycle, reconciliation and recovery | **Core / non-negotiable safety** | These are not optional infrastructure extras; they protect capital and preserve correct execution state. |
| LIVE execution | **Core capability with strict gate** | India-only and blocked until authoritative evidence and all applicable safety gates pass. No real orders in this development work. |
| UI / visual builder / production CLI | **Deferred** | The declared v0.1 product is a programmatic library; M4 did not include a visual editor or terminal. Revisit after a concrete user workflow is prioritized. |
| AI/ML strategy assistance and autonomous trading agents | **Deferred extension** | Not required to establish a correct deterministic strategy/backtest/paper foundation. Must consume existing contracts, never bypass risk or execution controls. |
| Additional global/crypto markets and FX | **Separate future market modules** | Market-neutral architecture is an enabling boundary, not a commitment to implement every market now. |
| Cloud, distributed workers, scheduling, broad automation | **Deferred** | Conflicts with the current local-first, no-unnecessary-server constraint and is not needed for core library delivery. |
| Universal Brain and general coding-agent orchestration | **Separate projects** | No QuantX runtime or acceptance dependency; keep optional integration outside the core. |
| Broad academic/technology research | **Time-boxed supporting activity** | Research is useful only when it resolves a named product decision or implementation blocker. Do not let open-ended research become a release milestone. |

## 5. Open GitHub issue disposition

All eight issues returned by the open-issue search were inspected. Their existence does not mean they all belong in the next implementation batch.

| Issue | Current subject | Scope disposition | Next action |
|---|---|---|---|
| #200 | Effective-dated India market-pack charges schedule and provenance | **Core India-market realism; active priority** | Continue the bounded tariff-source and calculation work. Keep unverified circular/attachment evidence explicitly blocked; do not guess rates or promote incomplete calculations. PR #329 is a contract-only slice and remains open. |
| #267 | LIVE risk evaluator authority and request-bound evidence | **Core safety blocker for LIVE** | Preserve pre-collection fail-closed rejection. Do not build another Dhan wrapper or weaken evidence requirements. Resume only when a credible authoritative provider/source is identified and evaluated. |
| #266 | LIVE daily-loss limit currently sees realized P&L only | **Core safety/accounting blocker for LIVE** | Preserve current explicit semantics. Do not infer unrealized/account-level P&L from incomplete Dhan files. Revisit when a coherent authoritative source/fixture set exists and accounting basis is settled. |
| #199 | Curated provisional public Python API and stability policy | **Useful adoption work; not a trading-functionality prerequisite** | Keep separate from core delivery. Review PR #333/current candidate against current main and its acceptance criteria; do not let it displace #200 or safety work. |
| #206 | Reusable broker/market-data/persistence conformance suite and JSON schemas | **Deferred ecosystem tooling** | Wait until #199's public API stability boundary is settled. Reuse canonical contracts; do not create a duplicate validator or treat internal SQLite JSON as public schema. |
| #203 | Dhan sandbox lifecycle capture and replayable fixtures | **Conditional integration evidence** | Proceed only if a verified non-production sandbox and safe, authorized access actually exist. Otherwise retain synthetic fixtures with explicit provenance and mark real sandbox scenarios unobserved. No production calls or real orders. |
| #205 | Python 3.13 validation matrix | **Deferred / blocked by validation infrastructure** | Keep current Python support range. GitHub Actions is disabled under standing project constraints; do not enable or rerun Actions or introduce paid CI. Revisit only if an authorized, free/local validation route can provide complete evidence. |
| #207 | Adversarial review execution tracker | **Governance/evidence tracker, not a product feature** | Keep as historical and cross-cutting safety traceability. Do not reimplement P0.1–P0.3; those remediations are recorded merged. Update only when a new concrete finding or evidence reconciliation requires it. |

### Issue-order conclusion

The current master work programme identifies Wave D / #200 as the next actionable workstream, while #266 and #267 remain blocked on authoritative source availability. This audit agrees with that sequence. It does **not** recommend switching to #199, #206, UI work, AI work, or another architecture migration as the next task.

The two LIVE risk issues remain product-critical safety blockers even though their next implementation step is blocked by missing evidence. A blocked issue is not permission to invent data or weaken controls.

## 6. Delivery roadmap

This roadmap is intentionally outcome-oriented. It does not create new speculative architecture milestones.

### Track 1 — Finish India-market realism (#200)

**Priority: next active implementation track**

- Resolve authoritative source acquisition and interpretation gaps for applicable Indian taxes/fees/charges.
- Preserve effective dates, source provenance, segment/product/side and calculation basis.
- Implement only rates and worked examples that are verified from authoritative sources.
- Keep Decimal arithmetic and deterministic calculation evidence.
- Fail closed or explicitly return unavailable for unsupported combinations.
- Independently review PR #329's exact current candidate/base before deciding whether to extend, split, or supersede it.

**Exit:** accepted India charge schedules and golden examples for the explicitly supported scope, with source and effective-date provenance; no guessed or stale defaults.

### Track 2 — Close LIVE safety evidence gaps (#267 and #266)

**Priority: gated; do not force implementation without sources**

- Preserve application-owned LIVE risk composition, request binding, freshness checks and rejection before reservation/submission.
- For #267, identify a credible authoritative provider for the full required evidence set; evaluate identity, completeness, pagination, timestamps, precision and contradiction behavior before implementing a provider.
- For #266, define the accounting basis for unrealized/mark-to-market loss and the required authoritative observations; do not silently redefine realized `daily_pnl`.
- Maintain the current no-LIVE/no-real-order development boundary.

**Exit:** authoritative source feasibility is established, the complete evidence contract is implementable, and exact-SHA tests prove fail-closed behavior and correct loss semantics. Until then, LIVE remains blocked.

### Track 3 — Broker integration evidence (#203), conditional

- First verify whether a real Dhan non-production sandbox exists for the required lifecycle scenarios and whether access is authorized.
- If not, do not simulate a sandbox claim. Continue deterministic synthetic/adversarial fixtures and document the unobserved scenarios.
- Keep credentials, account identifiers and personal data out of committed evidence.

**Exit:** replayable, sanitized fixtures with provenance distinguishing actual sandbox captures from synthetic tests, or an explicit documented unavailability decision.

### Track 4 — Adoption and ecosystem tooling (#199, then #206)

- Review the public API candidate separately; verify current base/head and acceptance evidence.
- Keep the exported API intentionally small and provisional; no mass re-export of internal modules.
- Only after the stability boundary is accepted, consider a reusable conformance kit and versioned public JSON schemas.
- Do not let API polish or schema publishing become a prerequisite for India charges or core safety.

### Track 5 — Product surface (deferred)

Revisit a CLI, visual strategy authoring, UI/dashboard, AI/ML assistance, or autonomous agents only after:
1. the core India workflows have a clearly demonstrated user journey;
2. a concrete user problem and acceptance criteria are written;
3. the feature can reuse existing strategy, research, paper and execution contracts;
4. it does not bypass safety, add mandatory paid/cloud services, or create a parallel runtime.

No implementation work for this track is authorized by this audit.

## 7. Definition of product progress

Measure progress by user-visible and safety-relevant outcomes, not by the number of architecture documents, abstractions, research reports, or test files.

A meaningful QuantX delivery outcome should satisfy at least one of:
- A user can define or run a supported Indian-market strategy through the canonical runtime.
- A strategy can be evaluated reproducibly using identified historical data, point-in-time market rules and realistic transaction costs.
- A paper workflow exercises the same relevant order/lifecycle semantics as the intended execution path.
- A supported broker integration gains a tested, documented capability without leaking vendor semantics into the core.
- A material risk, accounting, reconciliation, recovery or execution uncertainty is closed with exact-revision evidence.
- A concrete India-market requirement becomes supported with authoritative source provenance.

Architecture/refactoring is justified when required to deliver one of these outcomes or to preserve a named invariant. Otherwise it is deferred.

## 8. Scope-control rules for future proposals

Before accepting a new feature or research workstream, record:
1. the user-facing trading workflow or safety invariant it serves;
2. the current gap and evidence that the gap exists;
3. the smallest implementation boundary and existing canonical seam to reuse;
4. measurable acceptance criteria;
5. dependencies and evidence availability;
6. whether it is core, deferred, or a separate project.

Reject or defer work that only adds speculative extension points, duplicates an existing lifecycle/runtime/validator, requires a new mandatory cloud/paid service, or has no named caller and acceptance test.

One issue/PR should represent one coherent implementation slice. Keep exact base and candidate SHAs, isolated branches/worktrees for local changes, exact-SHA validation, and explicit evidence provenance. GitHub Actions remains disabled under the standing constraint. No live trading, real broker orders, production API calls, or sandbox interaction is authorized by this audit.

## 9. Limitations and non-claims

- This was a repository/documentation/issue reconciliation, not a local source-tree test run or full implementation audit.
- GitHub issue search returned eight open issues at the time of inspection; this is not a claim that no additional work exists in unindexed project systems or local worktrees.
- Existing test counts and coverage numbers are quoted only as repository/operator-reported historical evidence and remain bound to their original candidate SHAs.
- The audit does not certify production LIVE readiness, broker sandbox availability, tariff completeness, or the user's local working tree state.
- This document proposes a product boundary and delivery sequence. It does not close issues, merge PRs, release software, or authorize financial operations.

## 10. Recommended governing statement

> QuantX is an India-first, local-first, open-source algorithmic trading engine and platform library. It enables reproducible strategy research and backtesting, realistic paper execution, and carefully controlled broker integration through a market-neutral core and explicit Indian-market rules. Execution correctness, risk controls, portfolio/account integrity, reconciliation and recovery are first-class product capabilities. Additional markets, UI surfaces, AI/agents, cloud services and general-purpose automation are optional future extensions, not prerequisites for delivering the Indian-market product.

**Audit disposition:** Scope restoration recommended. Keep #200 as the next active implementation workstream; preserve #266/#267 as fail-closed LIVE blockers pending authoritative evidence; keep adoption/tooling work separate; do not expand the product surface during this delivery sequence.
