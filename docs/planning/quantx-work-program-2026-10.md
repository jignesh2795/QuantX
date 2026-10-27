# QuantX Master Work Programme — October 2026

**Status:** Active cross-workstream sequencing and reconciliation record

**Snapshot date:** 2026-10-27

**Baseline reviewed:** `main` at `a34ec73b3f9457079882ca99b895a8efeae23d73` (PR #281, trusted-clock freshness slice)

**Purpose:** Keep prior architecture, safety, India-market realism, global-market research, and release-readiness work in one progressable plan.

This is the canonical **active sequencing** document. GitHub issues remain the canonical individual acceptance/checklist records; `docs/STATUS.md` remains the implementation/evidence ledger; `docs/roadmap/README.md` remains the capability and milestone history. When an older status snapshot or planning note conflicts with the current issue acceptance criteria or this priority order, reconcile it before implementing. Do not infer completion from a branch name, documentation, or an old test count.

## 1. Repository snapshot and governance

- Latest `main` baseline verified during this reconciliation: `a34ec73b3f9457079882ca99b895a8efeae23d73`.
- Open PRs: **0** at snapshot time.
- Open issues: **20** after issue #181 was reconciled and closed on 2026-10-27.
- Active branch for this documentation reconciliation: `docs/quantx-master-work-program-2026-10`, based on `main`. This change is documentation-only.
- No new test suite, CI run, broker call, sandbox run, or LIVE operation was performed as part of this tracker update.

**Work rules:** use one coherent branch/PR per implementation slice; record exact base and candidate SHAs; keep validation evidence tied to its tested SHA; run the declared local validation gates with Dhan extra both enabled and disabled where applicable; distinguish local/operator-reported results from GitHub Actions; do not merge production code without exact-SHA evidence and required review. UNKNOWN and missing authoritative evidence are never PASS.

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
| LIVE trusted-clock freshness | Completed slice; not full evidence authority | PR #281; remaining work is #267 |
| QX-06 multi-leg semantics (#195) | **Design only**; no multi-leg execution implementation or capability claim | ADR-010; keep partial-leg failure and exposure semantics explicit |

QX-07 closure is a current update that supersedes the pre-merge snapshot still preserved in historical sections of `docs/STATUS.md`. The final slice's recorded local candidate validation was default **2,695 passed / 1 skipped** and Dhan-enabled **2,696 passed**, with Ruff/format, strict mypy, and independent review recorded as passing. These results belong to candidate SHA `a5219cf7616f34483e3c596d3feb47ac4c00673f`; they are local evidence, not GitHub Actions evidence, and do not establish production-broker or LIVE readiness.

## 3. Active priority order

Use the waves below as sequence, not as a commitment to implement every issue in one PR. Each issue retains its own acceptance criteria and scope.

### Wave A — LIVE risk authority and loss correctness

| Rank | Issue | State / next required outcome |
|---|---|---|
| **A1 — next** | [#267 LIVE risk evaluator authority and request-bound evidence](https://github.com/jignesh2795/QuantX/issues/267) | Highest priority. Block arbitrary/unapproved evaluator composition; bind risk inputs to the exact order, account, portfolio, broker connection and market context; require typed evidence with verifiable authority, observation time, freshness, completeness and explicit unavailable states. Missing/stale/foreign/contradictory evidence must block before reservation and submit. If a trustworthy adapter is absent, keep the sanctioned LIVE path unavailable/blocked. |
| A2 | [#266 LIVE daily-loss limit only sees realized P&L](https://github.com/jignesh2795/QuantX/issues/266) | Define realized/unrealized P&L, valuation basis/time, mark-to-market reversal, freshness and fail-closed semantics. Do not silently change the existing realized-only contract. Coordinate with #267's evidence model. |
| A3 | [#280 preserve operator block reason at startup](https://github.com/jignesh2795/QuantX/issues/280) | Disarm on process start without overwriting an existing operator/loss-breach reason; test fresh, enabled, already-blocked and persistence-failure cases. |
| A4 | [#189 Dhan startup/shutdown cleanup audit](https://github.com/jignesh2795/QuantX/issues/189) | Ensure cleanup errors remain observable and the primary startup failure is preserved; no network calls or adapter UNKNOWN-semantic changes. |

### Wave B — Strict boundary and deterministic-time hardening

| Rank | Issue | Next required outcome |
|---|---|---|
| B1 | [#271 exact UUID and Order runtime invariants](https://github.com/jignesh2795/QuantX/issues/271) | Enforce actual runtime contracts without coercion; audit affected paper/replay/backtest fixtures; preserve fingerprints, persistence and wire semantics. |
| B2 | [#269 exact LIVE broker-probe validation](https://github.com/jignesh2795/QuantX/issues/269) | `health()` only passes on exact `True`; connection/instrument/capability results must have exact expected shapes; malformed values return fixed fail-closed reasons. Issue records this as lower priority than the main authority/control-path gaps. |
| B3 | [#198 complete clock injection](https://github.com/jignesh2795/QuantX/issues/198) | Compare current call sites against architecture record 53; inject clocks where time changes behavior, preserve justified system/transport/audit timestamps, and add deterministic replay guards. |

### Wave C — Regression assurance

| Rank | Issue | Next required outcome |
|---|---|---|
| C1 | [#182 measured package-specific coverage floors](https://github.com/jignesh2795/QuantX/issues/182) | Measure the exact-base line and branch coverage for domain, execution and persistence, choose evidence-based floors, wire the local gate, and demonstrate both fail and pass behavior. |
| C2 | [#202 dead-module and Dhan transport coverage audit](https://github.com/jignesh2795/QuantX/issues/202) | Re-measure usage and line/branch coverage first; remove or justify suspected unused seams; improve deterministic transport tests without network access or inferred submit/cancel outcomes. |

### Wave D — India-market realism and public contract

| Rank | Issue | Next required outcome |
|---|---|---|
| D1 | [#200 effective-dated India charges schedule](https://github.com/jignesh2795/QuantX/issues/200) | Implement the approved **contract-only** slice behind the current charge interface. Keep all fixtures synthetic and clearly labelled. Do not populate unverified production tariff values or wire the schedule into paper execution yet. GST and stamp-duty applicability/effective dates are still data gates. |
| D2 | [#201 finite Decimal-only Money](https://github.com/jignesh2795/QuantX/issues/201) | Reject bool/float/string/non-finite amounts; enforce same-currency arithmetic only where needed; test consumer compatibility. |
| D3 | [#199 curated provisional public API](https://github.com/jignesh2795/QuantX/issues/199) | Define a small `quantx.api` with explicit stability tiers; don't mass re-export internals or import optional Dhan SDKs at import time. |

The charges contract/design is available in `docs/planning/india-market-charges-design.md`; source and unresolved rule evidence are recorded in `docs/planning/risk-charges-evidence-reconciliation.md`. These documents are design/research inputs only. The original risk/charges note proposed a different ordering; its final sequence is now explicitly superseded here. Do not treat a label such as `BROKER` or `RECONCILED` as proof of authority.

### Wave E — Integration proof, ecosystem and public readiness

| Rank | Issue / workstream | Next required outcome |
|---|---|---|
| E1 | [#203 Dhan sandbox lifecycle evidence](https://github.com/jignesh2795/QuantX/issues/203) | Only when sandbox access is safely available; produce replayable evidence fixtures and preserve a strict no-real-capital boundary. |
| E2 | [#206 broker/market-data conformance and schemas](https://github.com/jignesh2795/QuantX/issues/206) | Reusable contract suites and versioned schemas; keep provider capabilities explicit. |
| E3 | [#188 StrategySignal confidence contract](https://github.com/jignesh2795/QuantX/issues/188) | Settle semantics before Strategy SDK exposure; don't imply calibrated probability where none is measured. |
| E4 | [#190 security reporting policy](https://github.com/jignesh2795/QuantX/issues/190) | Publish only a real private disclosure route or record/configure the required repository setting; invent no email, SLA or bounty. |
| E5 | [#204 architecture overview and quickstart](https://github.com/jignesh2795/QuantX/issues/204), [#187 CONTRIBUTING.md](https://github.com/jignesh2795/QuantX/issues/187) | Align public wording with implemented/validated/supported distinctions and the actual local workflow. |
| E6 | [#205 Python 3.13 validation](https://github.com/jignesh2795/QuantX/issues/205) | Conditional on reliable CI/local infrastructure before widening the supported Python range. |

Issue [#207](https://github.com/jignesh2795/QuantX/issues/207) remains the meta review tracker; keep it updated as these workstreams move.

## 4. Global market and crypto work — retained, not yet implementation-ready

The product direction is globally architected; India is the initial trader and implementation focus, not the permanent architecture boundary. Digital assets—including evaluation of Delta Exchange India and Binance venue/product scopes—remain strategic targets, not claims of implemented, supported, or LIVE-eligible connectors.

- [The global architecture proposal branch](https://github.com/jignesh2795/QuantX/tree/docs/global-architecture-proposal-2026-10) remains docs-only with three documents under `docs/proposals/`: global product vision, staged global market-support roadmap, and comparative architecture audit plan. It is not merged into `main`.
- [The crypto market extension proposal branch](https://github.com/jignesh2795/QuantX/tree/docs/crypto-market-extension-plan) remains unmerged, with the crypto extension plan and global-market-separation updates.
- The comparative architecture audit is **not finished**: the existing document defines the research method and preliminary hypotheses; it is not yet a fully evidenced comparison against pinned source revisions of LEAN, NautilusTrader, Hummingbot, OpenAlgo, and relevant Indian-market projects.
- The next global-research deliverable is a source-backed comparison matrix: exact reference revision; inspected source/test paths; equivalent QuantX path; observed difference; practical consequence; adopt/adapt/defer/reject decision; test/migration requirements; confidence. Then update the market-support matrix and select **one** next data/research vertical based on demand, data/API access, legal/regulatory constraints and scope.
- Do not merge stale proposal branches wholesale, split the repo, broaden India-only LIVE policy, or infer crypto support from a region/asset-class enum. A new market requires explicit data/rule provenance, contract/conformance tests, paper/sandbox evidence and a separate LIVE eligibility review.

## 5. Progress protocol

For every implementation slice:

1. Read this programme, the relevant current issue, `docs/STATUS.md`, the architecture index, and the actual source/tests being touched.
2. Verify whether the work is already merged or the issue/status is stale before creating new work. One task, one bounded branch/PR; no redundant reimplementation of completed P0/QX slices.
3. State the exact base SHA, acceptance matrix, changed-path boundary and no-claims before validation.
4. Run focused tests, full suite, Ruff/format, strict mypy, diff checks and the repo's validation/release gate as applicable. Run with Dhan extra enabled and disabled when required. Capture real exit codes; no masked failures.
5. Obtain adversarial review for execution, persistence, risk, time or market-rule changes. Validation results attach only to the exact tested candidate SHA. GitHub Actions/CI is mentioned only when an actual relevant run exists.
6. After merge, reconcile the issue, update the appropriate section in `docs/STATUS.md`, record exact merge/candidate SHAs, and update this programme's status/next step. Keep dated historical snapshots but label them historical; do not leave a pre-merge “current” snapshot unqualified.

## 6. Immediate next task

**Proceed with #267, not another broad architecture rewrite.** Start by inspecting the current sanctioned LIVE composition and every call path that supplies `LiveRiskEvaluationInputs`. Map each required identity/evidence field to its authoritative source—or explicitly identify it as unavailable. Design the smallest application-owned composition and request-binding contract that cannot be self-authorized by a caller-shaped dataclass. Preserve trusted-clock freshness, India-only LIVE policy, durable disarmed gate, startup recovery, idempotency, UNKNOWN/quarantine, reconciliation and no-auto-retry invariants. If no authority-bearing evidence adapter exists, the accepted outcome is a tested block, not a fabricated adapter.

This plan records priorities and acceptance intent; it does not itself claim implementation, test, CI, sandbox, broker or LIVE results.
