# QuantX Status

## QX-08 v3.2.0 acceptance reconciliation — complete (2026-10-16)

PR [#234](https://github.com/jignesh2795/QuantX/pull/234) merged the final acceptance-evidence slice as merge commit `fe832fc21b5e714b3e1827a94e381cf84bb43746`, preserving the validated feature commit `9bd0d0e8fe983e3f415d97aed205a5175447635b` in history. The patch changes only `tests/unit/application/test_backtest.py` and `tests/unit/application/test_strategy_rehearsal.py`; no production code changed.

Exact-feature-HEAD validation was operator-reported at `9bd0d0e8fe983e3f415d97aed205a5175447635b`: focused suite **191 passed**; full suite **2,028 collected, 2,027 passed, 0 failed, 1 known optional-Dhan-extra skip**; Ruff check and format check passed for both changed files; strict mypy for `backtest.py` passed; `git diff --check` was clean. These are local results, not GitHub Actions or paid-CI results. No broker/LIVE operation was performed.

### QX-08 v3.2.0 acceptance-matrix traceability (T1–T8; G1–G3)

- **T1 / G3 — committed positions and order inventory:** `test_qx08_buy_and_hold_driver_state_and_callback_parity` (paper/backtest post-fill context parity), `test_active_order_persists_into_next_strategy_context_until_terminal_status`, `test_active_order_fact_retains_unknown_and_drops_canonical_terminal`, and the post-commit callback tests assert position facts after accounting and retained order status.
- **T2 — state-derived BuyAndHold:** `tests/unit/strategy/test_reference.py` covers known-empty entry, existing position, accepted/UNKNOWN orders, incomplete inventory, terminal-order retry, per-instrument independence, stateless repeat evaluation, and typed quantity bounds.
- **T3 / T7 — driver parity and repeatability:** `test_backtest_paper_order_sequence_parity`, `test_qx08_buy_and_hold_driver_state_and_callback_parity`, `test_qx08_accepted_without_fill_callback_and_order_inventory_parity`, `test_qx08_buy_and_hold_semantics_repeat_across_fresh_runs`, and deterministic timestamp/order/evidence regression tests cover matching decisions, outcome paths, and repeat runs.
- **T4 / G1 — timer phases and information cuts:** `tests/unit/strategy/test_timers.py` covers equal/past rejection, due-time then timer-ID ordering, uniqueness and end-of-horizon pending timers. The rehearsal/backtest driver suites cover timer dispatch before equal-timestamp cohorts, cohort failure blocking and later continuation, caller-order preservation, prior-only same-instrument history, latency/capability preflight, and current/future mark exclusion through `test_backtest_timer_snapshot_excludes_same_timestamp_mark_and_history`.
- **T4 / G2 — callback commit/error semantics:** `tests/unit/strategy/test_callbacks.py::test_post_commit_dispatch_attempts_all_fills_then_order_update` plus both driver-level `test_postcommit_callback_errors_complete_batch_then_latch_halt` tests assert complete deterministic notification attempts and halt behavior. PR #234 adds `test_qx08_accepted_without_fill_is_preserved_after_order_callback_error` for preserved accepted/submitted no-fill facts and post-commit halt in both drivers, and `test_rehearsal_preserves_future_effective_fill_and_halts_before_callbacks` for the exceptional temporal-integrity path.
- **T5 / G3 — incomplete and point-in-time evidence:** `tests/unit/strategy/test_engine_snapshot.py` covers unavailable/incomplete reasons, UNKNOWN order quantities, future evidence rejection, frozen views and bounded prior-only history; `test_backtest_as_of_observed_with_unusable_mark_stays_incomplete` covers stale marks; PR #234 adds `test_strategy_context_uses_tracker_snapshot_not_financial_state_input` so construction-time financial input is not presented as current account evidence.
- **T6 / T8 — paper-only and no-LIVE/no-broker boundary:** `test_session_rejects_non_paper_deployment`, `test_qx08_backtest_rejects_live_execution_context_for_bound_intents`, and `tests/unit/strategy/test_no_live_boundary.py::test_strategy_seams_have_no_broker_submit_or_scheduler_path` cover the runtime guard and AST boundary.
- **Typed parameters/history cross-cut:** `tests/unit/strategy/test_typed_params.py`, `test_prior_candle_history_rejects_invalid_limits`, and rehearsal history-bound tests cover canonical lexical forms, field-named errors, default-zero history and the 512-bar cap.

The bounded source/test reconciliation now has traceable evidence for every in-scope T1–T8 criterion and G1–G3 invariant. The parent Strategy Platform Flow path remains separate and out of QX-08 scope; no LIVE strategy execution, external scheduler, second accounting/lifecycle subsystem, or risk/execution-recovery redesign is introduced.


## QX-06 multi-leg design decision — accepted (2026-10-16)

[ADR-010: Composed Multi-Leg Order Workflow Semantics](architecture/adr/ADR-010-composed-multi-leg-order-semantics.md) resolves the architecture choice in issue #195: the first multi-leg vertical is an application-owned, sequential workflow of ordinary single-leg orders, not a native/atomic basket. The ADR defines stable workflow/leg identity, workflow-wide path-risk and margin admission, deterministic leg order, per-leg idempotency, partial-exposure/UNKNOWN handling, durable recovery requirements, and the explicit no-automatic-compensation/no-automatic-retry policy.

**Design only; no multi-leg execution is implemented or enabled.** Implementation is gated on canonical per-leg product/position-effect and derivative-contract decisions in #193/#194, plus a bounded trace of existing aggregate-risk, reservation, persistence and recovery seams. If those contracts cannot prove safe aggregate admission and restart/reconciliation, the workflow must fail closed. Native baskets, parallel submission, assumed spread-margin offsets, automatic flatten/hedge, and cross-broker atomicity remain unsupported.

## QX-04 order product and position-effect decision — accepted (2026-10-16)

[ADR-011: Order Product and Position Effect](architecture/adr/ADR-011-order-product-position-effect.md) settles the canonical contract choice for issue #193: product and position effect are per-order request semantics, not instrument attributes. Product vocabularies, support and compatibility defaults are resolved by the applicable versioned market-pack rules; Dhan adapters translate the resolved approved product to wire values. Position effect distinguishes OPEN, CLOSE, AUTO and absent/not-applicable, with AUTO requiring authoritative position evidence before approval. Fingerprints must include resolved product/effect and relevant rule identity. Current code does not yet implement this contract: `TradeIntent`/`Order` lack these fields, and Dhan product selection still comes from `DhanInstrumentRef.product_type`.

**Design only; issue #193 remains open for implementation.** The implementation must preserve the reserve-before-submit, idempotency, receipt-validation, and no-automatic-retry/UNKNOWN guarantees; update the canonical fingerprint path; and trace serialization/recovery as well as the adapter submit path.

## QX-05 derivative contract metadata decision — accepted (2026-10-16)

[ADR-012: Canonical Derivative Contract Metadata and Resolution](architecture/adr/ADR-012-derivative-contract-metadata.md) settles the ownership/resolution contract for issue #194. `Instrument` remains the owner of tradable instrument facts; a separate, canonical `Contract` record keyed by stable `InstrumentId` owns derivative underlying, expiry, strike and `OptionType`. The explicit resolution result must combine one canonical instrument with its point-in-time contract and instrument-rule versions/provenance. Options require complete option metadata; futures require underlying and expiry; missing, overlapping or malformed records fail closed.

The current code does not yet implement this decision: `Contract` embeds an `Instrument`, derivative fields are optional, `option_type` is a free string (and lowercase spelling is preserved), and `VersionedInstrumentRule` carries no derivative contract metadata. **Design only; issue #194 remains open for implementation** through catalog/resolution, risk and charges inputs, approved request, fingerprint, serialization/recovery and adapter validation.

## Current state — P0 LIVE-safety remediation active; QX-04/QX-05/QX-06 designs accepted; QX-08 acceptance complete; QX-09 complete

The consolidated LIVE-safety audit is recorded in [architecture/56-live-execution-safety-audit-and-priority.md](architecture/56-live-execution-safety-audit-and-priority.md), source spot-checked against `main` at `2ce04cf40952124e8b2ef0414cbc4ded9d660292`. Three new P0 remediation slices are open: [#239 durable kill-switch fail-closed/admission race](https://github.com/jignesh2795/QuantX/issues/239), [#240 startup must remain unready for unresolved recovery](https://github.com/jignesh2795/QuantX/issues/240), and [#241 post-submit receipt/persistence uncertainty](https://github.com/jignesh2795/QuantX/issues/241). The audit records source-confirmed behavior separately from the F1/F2 failure injections reported by the first audit and from source-tree-wide claims still requiring broader proof. This documentation pass did not run pytest, Ruff, mypy, or broker/LIVE operations and claims no new validation pass.

PR #221 merged QX-09 from `feat/qx-09-market-pack-checks-v1` at validated head `7793646e0e3d210e81364d39605ee3383e434723` as merge commit `1e4ebf4f4671e90dcdcafc1cda578182ab39d58b`. The PR covers 15 focused files (+5,746/−229); local validation was reported at the exact feature head, and no GitHub Actions results are claimed. Repository Actions are disabled by project policy.

PR #224 merged QX-08 M1 from `feat/qx-08-m1-engine-truth-context-v1` at validated feature head `0e9dd86401dae244b0c2546af528211a7039346d` as merge commit `8f1cc49c143fd5ee866be81fe366763700db1ac5` on 2026-10-16. M1 establishes immutable `StrategyContext` inputs, engine evidence/snapshot types, strict `TypedParams`, prior-only candle history, `EventTimeSupport` preflight contracts, and T8 no-LIVE boundary coverage. It does not implement callback/timer dispatch or paper/backtest driver wiring; those remain later QX-08 phases.

Exact-head OpenCode local validation at the PR feature head reported 1,945 passed, 0 failed, and 1 skipped (the known optional-Dhan-extra test); the focused strategy/application/execution/research set had 1,408 passed. Changed-file Ruff check and format check passed on the 12 intended paths, strict mypy passed on the seven changed production files, and `git diff --check` was clean. No GitHub Actions or paid CI result is claimed.

PR #226 merged QX-08 M2 from `feat/qx-08-m2-callback-timer-v1` at validated feature HEAD `75f8b0e2858d1ba11d1e7cd3c32f2fc6a6c2df1e` as merge commit `e150350ce747f88845227a70c35a9f94c8e7cd83` on 2026-10-16. M2 adds timer-request validation and deterministic timer/callback dispatch in rehearsal and StrategyEvaluationService backtests, with explicit precommit/postcommit failure semantics, event-time guards, retained active-order evidence, and T8 no-LIVE checks. Exact-HEAD local validation at the feature SHA was reported as 1,988 passed, 1 skipped, 0 failures/errors (1,989 collected); 1,451 focused strategy/application/execution/research tests passed; 21 T8/timer/callback/legacy-clock checks passed; Ruff format/lint and strict mypy on nine production files passed; and `git diff --check` was clean. The formatter-only commit `75f8b0e` was reported AST-identical across all seven touched Python files. This is operator-reported local validation; no GitHub Actions or paid CI result is claimed.

PR #229 merged QX-08 M3 from `feat/qx-08-m3-buy-and-hold-typed-bounds-v1` at validated feature HEAD `ebc67365ce589e50b0477de1b790885b4916c3e7` as merge commit `6f84259b8e6281576eead0831082067283baddeb` on 2026-10-16. M3 removes BuyAndHold's private entry state and derives BUY/HOLD decisions from engine position/order evidence, fails closed when inventory evidence is unavailable/incomplete or a position/order is present, uses strict typed quantity projection, and retains bounded prior-only candle history. BuyThenClose keeps its original legacy quantity parsing via an isolated compatibility helper. Exact-HEAD local validation at the feature SHA was reported as 2,018 passed, 1 skipped, 0 failures/errors (2,019 collected); 247 focused tests passed; Ruff check/format, strict mypy on `reference.py`, and `git diff --check` passed. The changed-file set was exactly eight intended Python files. This is operator-reported local validation, not GitHub Actions evidence. No Actions or paid CI was used; no broker/LIVE operations were performed.

PR #232 merged QX-08 M4 from `feat/qx-08-m4-driver-parity-v1` at validated feature HEAD `40559841bc94e3b4c1c7482b21528300c895d7e4` as merge commit `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4` on 2026-10-16. M4 adds explicit caller-owned simulated execution-context binding for bare intents on the StrategyEvaluationService backtest path, rejects unsupported modes, preserves existing intent contexts and the legacy callable path, and adds BuyAndHold state/callback parity, determinism, LIVE-context rejection, and accepted/submitted-without-fill inventory coverage. Exact-tip local validation at the feature SHA was reported as 153/153 focused tests and 2,023 full-suite tests with 0 failures and 1 known optional-Dhan-extra skip; Ruff check/format on the two changed files, strict mypy on `backtest.py`, and `git diff --check` passed. The changed-file scope was exactly the two intended files. This is operator-reported local validation; GitHub Actions remain disabled, and no broker/LIVE operations were performed.

PR #218 merged the independently validated M4.1 feature head `d99c12f3ae051f992722bee2bc8ea3253032fdc8` from `feat/m4-1-strategy-paper-rehearsal-v1` as feature merge commit `a0bf101b6f6bb87d11460cefb199932a768d6335`. That SHA is the PR #218 feature-merge anchor, not the current `main` HEAD. PR #219 subsequently merged the cross-document status rebaseline in commit `3893ea4f19bed3f6b4c0b5cdc70da9167e0e90b9` on 2026-10-14.

M4.1 adds a deterministic, single-use Python strategy rehearsal from registry/runtime evaluation through deployment-owned execution-context binding, risk/policy preparation, and the existing paper executor. It admits enabled PAPER deployments only; it creates no broker-submit path and changes no execution/recovery semantics. The timestamp regression fix derives submission nanoseconds and order creation time from the market event and rejects strategy signal timestamps that differ from event time.

Independent local validation at the exact feature head reported **22 rehearsal tests passed, 177 focused regressions passed, and 1,713 full-suite tests passed with 0 skipped** in an environment where the optional Dhan SDK was installed. Repo-wide Ruff and format checks passed; strict mypy passed across 183 files both with and without the Dhan extra; frozen Dhan sync succeeded and its focused slice passed 130 tests; `git diff --check` was clean. These are local test results, not GitHub Actions evidence. No Actions or paid CI was used.

M4.1 is the first Strategy Platform vertical, not the full parent M4 exit. QX-09 (issue #197) is complete in PR #221. The normative QX-08 design contract remains [docs/implementation/qx-08-engine-truth-strategy-context.md](implementation/qx-08-engine-truth-strategy-context.md), v3.2.0. QX-08 implementation milestones M1, M2, M3, and M4 are complete in PRs #224, #226, #229, and #232 respectively. PR #232's validated feature HEAD is `40559841bc94e3b4c1c7482b21528300c895d7e4`, merged as `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4`. The QX-08 v3.2.0 acceptance-matrix reconciliation is complete; see the closeout section at the top of this file. Issue #196 is closed. The current execution-safety remediation order is recorded in architecture record 56 and issues #239–#241. The parent Strategy Platform M4 exit still includes a first Flow path with shared runtime semantics; that is separate roadmap work and is explicitly outside QX-08. QX-08's callback-enabled path fails closed on nonzero-latency execution configurations because future-effective fills require a separate event-time execution integration, which is out of scope. External scheduling, AI/agents, and LIVE strategy execution remain outside the QX-08 scope.

## Historical merge checkpoint — PR #214 (QX-03 canonical order lifecycle)

At this historical checkpoint, PR #214 advanced `main` to `1fbddc69982722a03ba13bdde76aa8aa76c85d94` (merge commit); that is not the current `main` head. The merged PR #214 head was
`675d351915671168a0e0c4af38ba82f05c85022f`; a post-merge audit proved the
merged tree and the tested tree byte-identical (`git diff 675d351 1fbddc6`
empty, merge parents exactly `1aaf27b` + `675d351`). The QX-03 canonical
order lifecycle (ADR-009) reached `main` in three sequenced slices: PR #213
delivered the first migration slice (canonical `OrderStatus` vocabulary
with `SUBMITTED`, a consolidated evidence-preserving reducer, and trusted
reconciliation entrypoints; merged as `2785fbd`); PR #214 added Dhan
lifecycle goldens for all seven vendor statuses and explicit paper DAY/IOC
semantics; and the merged PR #216 contract added cumulative-observation
receipt evidence (`ExecutionEvidenceKind`) with legacy-payload
compatibility. Issue #192 is closed as completed (2026-10-14), as is
follow-up issue #215.

The following is implementer-reported **local validation** at the tested
head `675d351`, not GitHub Actions results and not independently executed
in this reconciliation:

- Full default suite: **1,690 passed, 1 skipped** across three consecutive
  runs, plus a passing warnings-as-errors run.
- Dhan-extra suite (`uv sync --frozen --extra dhan`): **130 passed**.
- Focused Dhan lifecycle goldens: 6 passed; goldens plus paper suite:
  53 passed; broader execution/Dhan/persistence/application suites:
  1,106 passed, 1 skipped.
- `uv run ruff check`: all checks passed. `uv run ruff format --check src tests`:
  350 files already formatted. `uv run mypy`: no issues in 182 source
  files, with the Dhan extra both absent and installed. Frozen sync and
  `git diff --check`: clean.

No GitHub Actions or paid CI was triggered for this evidence. No API keys,
broker credentials, network-dependent tests, or real broker orders were
used.

## Historical v0.1 acceptance and R1-C completion baseline
**v0.1 acceptance base:** `6f771b5044d7c971b5da2301901534a5156df361` (PR #164 merge; verified before this status update).

**R1-C1 through R1-C12:** complete.

**R1-C13:** complete through C13.8, including durable research persistence, research-run orchestration and lifecycle binding, rehydration, experiment comparison/association/metadata persistence, experiment detail read, and the experiment write boundary.

**R1-C14:** complete through C14.9, including provider/MarketDataPort composition, registered dataset identity, explicit quality evidence, durable candle persistence/readback, research provenance binding, and the end-to-end deterministic lifecycle proof. PR #158 is merged to `main` at the post-C14 integration base above.

**V0.1 local-first host and integration readiness:** rebaselined at the acceptance base. PR #164 (host-composed restart regression) and PR #175 (optional Dhan SDK typing fix) are merged. Per ADR-008, v0.1 ships as a programmatic local-first library on the `DhanHostConfig` + `build_dhan_host_runtime()` → `DhanHostRuntime.start()` / `close()` bootstrap contract; the CLI is deferred and `docs/roadmap/feature-priorities.md` is aligned. The normative checklist in `docs/architecture/28-v0.1-acceptance-criteria.md` records every required criterion PASS with exact evidence (full suite 1483 passed, Ruff zero findings, strict mypy clean with and without the Dhan extra) and closes the release gate for the declared scope. Validation remains local; no real-broker LIVE-readiness claim is implied. This rebaseline changes documentation and one formatting-only test collapse; no production behavior changed.

The repository contains an implemented domain, execution, research, India-market, integration, reconciliation, and deterministic research foundation. Historical validation records below are retained as evidence/history and do not define the current milestone.

**Latest externally validated recovery milestone:** `feat/production-recovery-entrypoint` at `efa4798a76d3576f31b5a2127381fb990c6a0915` with 665 passed, 0 failed, 0 errors, 0 skipped. The earlier 635-test checkpoint remains the last independently documented baseline on the pre-entrypoint recovery branch.

## Post-PR #33 validation evidence

The LIVE startup/readiness and trading-gate hardening merged in PR #33. Claude's local sandbox validation of the PR branch reached **813 passed tests, 0 failed** after aligning the affected fixtures with the new runtime/evidence contracts. Equivalent test fixes are included in the merged mainline, with an additional explicit unscoped negative-case correction. This is local validation evidence, not GitHub Actions evidence; Actions is not used as a repository gate while billing is disabled.

## Validation baseline

A prior externally reported checkpoint for the production-recovery stack was **665 passed, 0 failed, 0 errors, 0 skipped** at `efa4798a76d3576f31b5a2127381fb990c6a0915`. This validation was run externally with OpenCode on `feat/production-recovery-entrypoint`; changed-file Ruff and `git diff --check` were clean. At that time, repo-wide Ruff reported 272 pre-existing errors. No production-broker end-to-end execution was claimed.

This checkpoint validates the LIVE durability hardening, pending-recovery corruption isolation, and explicit startup lifecycle: LIVE requires a UnitOfWork-backed transaction path; completed broker submissions retain a durable receipt even when idempotency completion is uncertain; direct LIVE dispatcher/adapter bypasses are blocked; durable trading-gate state survives restart; pending LIVE reservation context is persisted and reconstructible across a simulated process restart; malformed pending contexts are isolated as per-context recovery failures; the default all-required recovery path can resolve with local position/account evidence; concurrent recovery passes resolve a pending reservation at most once; and an explicit application runtime runs pending recovery once before startup completes. The 635-test suite completed with zero failures, errors, or skipped tests.

The 635-test validation was performed against the branch head after fast-forward sync at `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c`. The only Ruff finding was the pre-existing `I001` import-order issue in `src/quantx/application/execution.py`; a subsequent import-only cleanup was committed at `5817ce0f9cb2103f9ba05abfefa7495c5f2ec342`. `git diff --check` was clean; the local `uv.lock` modification was pre-existing environment noise and remained untouched. The import-only cleanup has not been independently re-run through the full suite in this environment.

This is the reported validation result for the checked commit. The available GitHub Actions status endpoint does not show an independent workflow run for this checkpoint, so this document does not claim GitHub CI independently executed that suite.

## Historical local validation evidence (R1-C14 vertical proofs)

Local validation on the C14.7 vertical-proof branch `feat/r1c14-dhan-market-data-host-wiring-test-v1` (base `e72287ce84afdd8393bd8c4203e7c82dd2629abf`) reports **1399 passed, 0 failed, 1 skipped** in the full suite (the skip is the optional-Dhan-SDK test; no warnings were emitted across two consecutive runs). Repo-wide Ruff reports **zero findings**; strict mypy reports **no issues in 179 source files**; `git diff --check` is clean. This is local validation evidence; no GitHub Actions run is claimed and no production-broker end-to-end execution was performed.

Local validation on the C14.8 binding branch `feat/r1c14-research-provenance-binding-v1` (base `0196ceec6f46231eb5c9be0e6d5b983bfaa4746d`) reports **1409 passed, 0 failed, 1 skipped, 1 warning** in the full suite (the skip is the optional-Dhan-SDK test; the warning is the pre-existing `SyntaxWarning` in `tests/unit/research/test_storage_filesystem.py`). Repo-wide Ruff reports **zero findings**; strict mypy reports **no issues in 180 source files**; `git diff --check` is clean. This is local validation evidence; no GitHub Actions run is claimed and no production-broker end-to-end execution was performed. It binds declared dataset identity to the canonical research-run identity and does not yet prove the full provider-to-research lifecycle.

Local validation on the C14.9 proof branch `feat/r1c14-end-to-end-deterministic-proof-v1` (stacked on the C14.8 head `62f87b657cf66a3f078b069a6e522ec3801b6046`; not on `main`) reports **1410 passed, 0 failed, 1 skipped, 1 warning** in the full suite (the skip is the optional-Dhan-SDK test; the warning is the pre-existing `SyntaxWarning` in `tests/unit/research/test_storage_filesystem.py`). Repo-wide Ruff reports **zero findings**; strict mypy reports **no issues in 180 source files**; `git diff --check` is clean. This is local validation evidence; no GitHub Actions run is claimed and no production-broker end-to-end execution was performed. It proves one declared dataset identity flowing deterministically from provider retrieval through durable persistence and dataset-scoped read into provenance binding and a completed, reopen-verified research run.

Recent continuation/recovery work includes:
- explicit continuation lifecycle reconstruction from authoritative receipt evidence;
- continuation-chain lineage and aggregate fill validation;
- idempotent continuation dispatch claims;
- pending/recoverable/resolved continuation recovery states;
- validation that reused continuation claims match authoritative receipt identity, quantity, account, and broker connection;
- conservative recovery of execution state rather than inference from an uncertain submission;
- durable trading-gate state persisted behind a pluggable state-store boundary, with SQLite restart coverage;
- versioned pending LIVE execution context persisted with idempotency reservations and reconstructible after restart;
- SQLite schema v2 migration coverage for pending context and durable trading-gate state;
- deterministic pending LIVE recovery with per-context failure isolation and no-submit semantics;
- malformed persisted-context isolation with reservation/context identity checks;
- explicit, one-shot application startup lifecycle for recovery-backed startup;
- broker-returned `UNKNOWN` LIVE receipts remain durably PENDING for reconciliation rather than completing idempotency.

## Architecture direction

- modular monolith first; distributed-ready later
- event-driven/domain-driven core
- ports and adapters
- capability-based integrations
- plugin-first extensibility
- Indian-market/F&O-first domain model
- data, control, and execution plane separation
- deterministic research, replay, and simulation
- explicit provenance and point-in-time market rules
- fail-closed live execution
- reconciliation rather than inference for uncertain broker outcomes
- local-first deployment with clear integration seams

## Current implementation track

QX-09 market-pack pre-trade-check pipeline is complete via PR #221 (validated feature head `7793646e0e3d210e81364d39605ee3383e434723`; merge commit `1e4ebf4f4671e90dcdcafc1cda578182ab39d58b`). Issue #197 is complete. QX-08 issue #196 has completed implementation phases M1 in PR #224, M2 in PR #226, M3 in PR #229, and M4 paper/backtest driver parity in PR #232 (validated feature HEAD `40559841bc94e3b4c1c7482b21528300c895d7e4`; merge commit `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4`). The QX-08 v3.2.0 acceptance-matrix reconciliation is complete; see the closeout section at the top of this file. Issue #196 is closed. The current execution-safety remediation order is recorded in architecture record 56 and issues #239–#241. Flow authoring/runtime parity, external scheduling, AI/agents, and LIVE strategy execution remain outside QX-08 scope and must not be implied by these completed implementation phases. Execution/recovery safety boundaries remain frozen unless a concrete reproducible invariant violation is proven. The repository now covers idempotency, execution receipts, order lifecycle reconstruction, account/connection identity, broker-order reconciliation, bounded evidence refresh, uncertain-submission recovery, partial-fill continuation/recovery, durable trading-gate state, durable pending LIVE execution context, malformed-context isolation, explicit recovery-backed application startup, fail-closed handling of broker-returned UNKNOWN LIVE receipts, and concrete production startup composition with identity-bound Dhan recovery evidence. The Dhan production host adapter (`DhanHostConfig`/`DhanHostRuntime`) composes credentials/transport construction, exact account/connection registration, and one-shot recovery-backed startup with no broker-submit surface and no new execution semantics. A vendor-neutral local market-data store (`MarketDataStore`, SQLite-backed) persists canonical quotes/candles with exact Decimal fidelity, deterministic chronological retrieval, idempotent-duplicate/conflicting-duplicate semantics, and schema v3 migration; Dhan remains an adapter above that storage boundary. A vendor-neutral dataset catalog registers immutable `DatasetVersion` identities with idempotent-duplicate/conflicting-duplicate semantics and local JSON metadata persistence, without verifying source content or performing ingestion. A deterministic historical-data quality seam analyzes canonical candle collections for structural soundness and assesses completeness only against an explicitly supplied expected timestamp set, reporting UNKNOWN completeness otherwise, without repairing data or verifying source files. A dataset-backed historical research access seam resolves a registered `(dataset_id, version)` through the catalog and reads version/source-scoped canonical candles from `MarketDataStore` without source verification, backtesting, simulation, or scheduled operation. A canonical historical candle ingestion bridge (`research/market_data_ingestion.py`) connects `MarketDataPort` to `MarketDataStore` with no scheduling, retry, caching, or network behavior; there is no claim of scheduled ingestion, production historical-data operation, or real-broker end-to-end execution. Historical research observations (`HistoricalObservation`) now preserve canonical candles losslessly alongside quote snapshots: `HistoricalObservation.from_candle` keeps the exact `Candle` (instrument, timeframe, timestamp, OHLCV) with no Quote projection and no synthetic bid/ask, `HistoricalDataSeries`/`HistoricalReplay` stay payload-neutral over both payload types, and dataset-backed candles convert through `research/dataset_access.py` without touching `MarketDataStore`, catalog, or identity rules. This does not implement backtesting or execution simulation, does not verify source integrity, and does not add scheduled/production historical ingestion. The deterministic backtest path now accepts candle-backed replay frames through the existing event and reference-price contracts (candle events carry the exact `Candle` with `MarketDataType.CANDLE`; bar-close is the reference price per the strategy preparation contract), while quote-based paper execution stays explicitly unavailable for candles via a `BLOCKED` disposition instead of synthetic bid/ask. A minimal deterministic `BASIC_BAR` fill model now prices candle MARKET orders at the observed bar close through the existing `FillModel` seam (`CandleFillModel`, routed by `DataAdaptiveFillModel` without changing quote behavior); limit/stop orders propose no fill rather than an inferred one, and all fills remain `SIMULATED_EXECUTION` with explicit assumptions. Each fill proposal now carries its selecting model identity (`QUOTE`/`paper-core-v0.3` or `BASIC_BAR`/`basic-bar-v2`) onto the engine receipt, so mixed quote/candle runs can no longer inherit a misleading profile label; quote receipt metadata is unchanged. Intrabar semantics, partial fills beyond the existing ratio, slippage beyond the existing model, and richer bar-model provenance remain future M3 work. `CandleFillModel` has since grown a conservative close-cross LIMIT rule (`basic-bar-v2`): BUY fills only at or below the limit, SELL only at or above it, priced at the exact bar close, with high/low never triggering fills; STOP/STOP_LIMIT still propose no fill. `CandleFillModel` now classifies stop triggers explicitly (`basic-bar-v3`): a touch confirmed by the close fills at the close, a touch without confirmation is ambiguous and blocked rather than priced, untouched stops rest unfilled, and STOP_LIMIT stays rejected because post-trigger limit ordering is unknowable from OHLC; single-step lifecycle is unchanged. `BacktestResult` now carries experiment-level `BacktestFidelity` reusing the research `ResultQuality` vocabulary (models, evidence types, determinism, limitations) with per-receipt model identity; missing research-provenance inputs remain explicitly unavailable rather than fabricated. `CandleFillModel` (`basic-bar-v4`) accepts an optional Decimal candle-volume participation rate bounding proposed quantity by that share of the observed bar volume (zero volume means no fill); the cap is recorded as a modeled assumption, never observed liquidity, while pricing, triggers, quote behavior, and the existing partial-fill ratio remain unchanged. The pre-existing deterministic `slippage_bps` control is now Decimal-strict at construction, applies unchanged after price discovery (BUY multiplies, SELL divides, per the pinned engine semantics), records a `reference_price=` token only when actually applied, and is noted in backtest fidelity; no new slippage parameter was introduced.

`PendingExecutionRecoveryRunner` remains a deterministic application service with no broker-submit capability. The current hardening branch also makes LIVE execution depend on a started recovery-backed `ApplicationRuntime` and adds submission-time trading-gate authorization spanning durable reservation and the broker call. `ApplicationRuntime` now provides the explicit one-shot startup lifecycle seam: it requires a recovery hook, runs it synchronously before marking the runtime started, rejects repeated starts, and leaves startup failed if recovery infrastructure raises. `ProductionRuntime` now provides the concrete process-composition boundary: it owns the durable SQLite lifecycle, accepts explicit registry configuration, delegates to the recovery-backed `ApplicationRuntime`, and closes persistence on composition failure. It intentionally does not construct credentials, broker transports, or deployment-specific services. Therefore this is validated production composition, not a claim of an executable CLI/service deployment or real-broker end-to-end startup.

The continuation implementation deliberately remains persistence-agnostic: it consumes authoritative receipt/reconciliation contracts and does not introduce a database or broker network dependency by itself.

## Execution/recovery adversarial findings — latest recorded audit

No outstanding adversarial finding. The record below is historical: the review of the 20-commit recovery sequence identified two additional LIVE control-path gaps — startup recovery was not a required dependency of `ExecutionOrchestrator`, and the gate check could race with broker submission. Both were integrated (recovery-backed `ApplicationRuntime` startup dependency and submission-time trading-gate authorization) and are covered by the current green suite; they are not pending validation. A new finding will be recorded here only with exact evidence of an actual unresolved issue.

## Documentation policy

Architecture documents distinguish implemented/current behavior, target architecture, and roadmap/future capabilities. Historical batch records should not be treated as current implementation state unless explicitly marked as historical.

## R1-C9 milestone

R1-C9 multi-instrument account-state synchronization is implemented and merged (squash `53022d15ff9e209e78739c1b87462635a8c2e174`). The final implementation head was `6bf81fb2571da7423e25865b6c859bea6f5e78eb` on `feat/r1c9-remediation`. External OpenCode/local revalidation reported **1185 passed, 0 failed** in the full suite; the focused C9/replay set reported **23 passed**. Changed-file Ruff had **0 new in-scope findings**, strict mypy had **0 errors in the changed production files**, and `git diff --check` passed. C9 adds an explicit `AccountStateSamplingPolicy` (`EXACT_CURRENT` default, `AS_OF_OBSERVED` opt-in) mapped onto the existing tracker behavior, plus a replay-boundary extension so `HistoricalReplay` accepts multiple single-instrument series merged deterministically, while `HistoricalDataSeries` remains strictly single-instrument. No LIVE, broker, reconciliation, recovery, risk, persistence, or accounting semantics were changed.

## R1-C8 milestone

R1-C8 historical account-state valuation provenance is implemented and merged in PR #69. The final revalidated implementation head was `57ddc1e5e65a55e8cea0296e9120b704e9224951`; it was squash-merged to main as `d5a8776d26e773552b1ba072fcffc827176c0183`. External revalidation reported **1175 passed, 0 failed, 0 errors, 1 skipped** in the full suite, with the optional Dhan SDK test skipped; the focused C8/C4/C7 regression set reported **89 passed**. Changed-file Ruff passed with zero new in-scope findings, strict mypy passed for `historical_account_state.py`, and `git diff --check` passed. C8 adds immutable valuation provenance to historical account-state snapshots without changing mark-selection, accounting, risk, LIVE, broker, reconciliation, retry, UNKNOWN, or recovery semantics.

## R1-C7 milestone

R1-C7 time-indexed historical account-state sampling is implemented and merged in PR #67. The final revalidated implementation head was `92f3a7915a70b16f43d98eae8f0ad36d79c3af65`; it was squash-merged to main as `3a35d32ce60eecb155027bb59a69edd94e5b4cff`. External revalidation reported **1173 passed, 0 failed, 0 errors, 1 skipped** in the full suite, with the optional Dhan SDK test skipped; the focused C7/execution/backtest regression set reported **76 passed**. Changed-file Ruff had **0 new in-scope findings**, strict mypy passed on the three changed production files, and `git diff --check` passed. The final implementation adds timestamped valuation marks and an additive pre-frame `account_state_series` with exact-current-mark fail-closed semantics while preserving the C4 receipt-driven `account_states` path. No LIVE, broker, reconciliation, retry, UNKNOWN, recovery, risk, or accounting semantics were changed.

## R1-C6 milestone

R1-C6 execution-fidelity hardening is implemented and merged in PR #65. The final validated implementation head was `5a58318c3978b3a78da32847d717e8bc842a8ac8`; it was squash-merged to main as `8067e5f3b81344698b818d950373bbcc477c170a`. External revalidation reported **1168 passed, 0 failed, 0 errors, 1 skipped** (the optional Dhan SDK test). Changed-file Ruff, strict mypy for the two changed production files, and `git diff --check` all passed. The final C6 implementation touched only the paper/research execution-fidelity path and test/docs surfaces; it did not expand LIVE, reconciliation, retry, UNKNOWN, recovery, broker SDK, persistence, or integration boundaries.

## V0.1 and R1-C roadmap context (historical baseline)

V0.1 local-first host and integration readiness is acceptance-complete for the declared programmatic-library scope (ADR-008): the acceptance audit is done, the host-composed restart proof (PR #164) and the optional-SDK typing fix (PR #175) are merged, the CLI is explicitly deferred, and the release gate is closed per `docs/architecture/28-v0.1-acceptance-criteria.md`. R1-C13/C14 records below are historical milestones, not current work. Treat execution/recovery safety boundaries as frozen unless a concrete invariant violation is proven; no production-broker end-to-end execution has been performed.

C14 establishes a deterministic, provider-neutral historical dataset ingestion application boundary that composes the existing `MarketDataPort`, `DatasetCatalog`, historical-data quality, `MarketDataStore`, dataset-backed research access, and research provenance seams. Dataset identity is pre-declared and authoritative; observations remain lossless; completeness remains evidence-bound; persistence semantics remain centralized; and provider-specific behavior remains outside the dataset domain.

The protected C14 salvage sources are `feat/m2-dataset-ingestion-workflow-v1` and `feat/dhan-host-market-data-wiring-v1`. They are not current implementation branches and must not be merged wholesale; their unique tests/design are source material for C14.

C14 explicitly defers scheduling, retry orchestration, streaming, production historical-data service, distributed ingestion, cloud storage, generic ETL, UI, AI/ML, optimization, and broad broker expansion.

GitHub Actions is not a repository validation gate while billing is disabled; OpenCode/local validation remains the execution gate. No production-broker end-to-end execution has been performed.
