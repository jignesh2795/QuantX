# QX-08 Design Brief v3.2 — engine-truth StrategyContext and deterministic callbacks

**Version:** 3.2.0 (normative after merge; supersedes v1/v2/v3.0/v3.1)
**Repository:** jignesh2795/QuantX
**Audit baseline:** b994acb752209facf4de3d1caa8176512a843fdb
**Tracked requirement:** [Issue #196](https://github.com/jignesh2795/QuantX/issues/196)
**Completed dependencies:** [PR #221](https://github.com/jignesh2795/QuantX/pull/221), merge 1e4ebf4f4671e90dcdcafc1cda578182ab39d58b; [PR #222](https://github.com/jignesh2795/QuantX/pull/222), merge b994acb752209facf4de3d1caa8176512a843fdb.
**Scope:** design/documentation only. This document does not claim implementation or test completion.
**Gate:** the design gate passes when this document and the synchronized status/roadmap updates merge together. Every implementation phase remains separately gated on tests passing at its exact reviewed SHA.

MUST / MUST NOT are normative. Types and test names marked NEW/proposed do not exist at the audit baseline unless separately implemented.

## 1. Objective and StrategyContext contract

At the audit baseline, src/quantx/strategy/context.py exposes only event and ir. StrategyRuntime evaluates market-data events only, and BuyAndHoldStrategy retains private _entered state. QX-08 adds an immutable view of engine-owned state without adding a broker-submit path or another execution/accounting lifecycle.

The proposed StrategyContext contains:

- event: MarketDataEvent | None — present for on_market_data; None for on_timer.
- ir: canonical immutable StrategyIR.
- as_of: timezone-aware UTC logical time from the injected deterministic driver clock.
- engine: immutable EngineStateSnapshot (NEW), covering positions, active/unresolved orders, and account/portfolio evidence.
- history: immutable tuple of canonical Candle observations only, strictly prior and same-instrument, bounded by history_bars. Quotes/ticks are not synthesized into candles.
- params: strict TypedParams projection (NEW) over canonical IR strings.

Every exposed object must be deeply immutable: frozen records/value objects and tuples, without mutable lists/dictionaries. The context exposes no execution mode, broker object, credentials, submit capability, or LIVE-capability marker.

EngineStateSnapshot distinguishes known-empty evidence from unavailable/incomplete evidence. Empty tuples alone never mean flat/no open orders. Position, order, and account dimensions each carry explicit availability/completeness and a reason when unavailable/incomplete. UNKNOWN is never PASS and never zero.

## 2. Strategy callbacks (D1 settled)

The only intent path remains on_market_data(context) -> StrategyResult -> StrategyRuntime validation -> preparation -> risk/policy -> existing execution. Optional callbacks are observe-only and return None; missing callback methods are no-ops:

- on_fill(context, fill)
- on_order_update(context, update: OrderUpdateFact) where OrderUpdateFact (NEW) is an immutable view of stable client_order_id, canonical status, ordered fill facts or fill totals, remaining quantity when authoritative, and status evidence/time.
- on_timer(context, timer: TimerInvocation) where TimerInvocation (NEW) identifies the fired timer and immutable registration fields.

Callbacks cannot emit TradeIntent, register/cancel timers, mutate engine facts, or bypass the normal intent path. Only a validated StrategyResult may carry TimerRequest values. Valid timer requests are registered immediately after runtime-result validation and before preparation/risk/policy/execution; a later risk/policy rejection does not roll the timer back. Failed/invalid strategy results register no timers. Strategy-local mutations before a pre-commit exception are not generically rolled back.

## 3. StrategyIR and typed parameters

StrategyIR is unchanged: parameters remain a sorted, unique tuple of (str, str); canonical strings remain the equality/fingerprint identity. TypedParams is a read-only projection, never a second store.

TypedParams provides strict string, boolean, integer, and Decimal getters. Every parse/range error names the field. Missing required values fail unless the caller explicitly supplies a default. Canonical forms are fixed: strings are returned unchanged; booleans accept exactly lowercase true or false; integers accept 0 or a minus sign followed by a nonzero ASCII digit and then ASCII digits (no plus, whitespace, decimal, exponent, or leading zeros); Decimal accepts fixed-point base-10 with no surrounding whitespace, exponent, non-finite token, or leading zeros other than integer part 0. No silent coercion/fallback. Financial quantities, prices and money use Decimal, never float.

history_bars is validated at the history request/getter, not by changing StrategyIR construction:
- absent means 0;
- accepted range is integer 0..512 inclusive;
- malformed, boolean-like, non-integral, negative, greater-than-512, or noncanonical lexical values fail closed and name the field;
- invalid values are never clamped or interpreted as unlimited.

## 4. G1 — timers, causality and no look-ahead

TimerRequest (NEW) is an immutable StrategyResult field containing timer_id, instrument, and timezone-aware due_at. QX-08 supports one-shot, instrument-scoped timers only: no payload, recurring/global timer, cancellation protocol, or external scheduler.

- Timer requests are accepted only from a validated on_market_data result.
- timer_id is non-empty and unique for the strategy run. Duplicate/reused IDs are rejected; IDs are the fixed equal-time tie-breaker.
- instrument must equal the registering event's instrument.
- due_at must be strictly later than the registering event timestamp; equal/past timestamps are rejected explicitly.
- on_timer cannot register or cancel timers.

Before processing any event cohort at timestamp T, dispatch all already-registered timers with due_at <= T, across instruments, sorted by (due_at, timer_id). A cohort is all input events whose timestamps equal T. Timers are dispatched before any market frame in that cohort is observed/incorporated. SimulatedClock advances monotonically to each due_at and then to T; no sleep, wall clock, or external scheduler is allowed.

Driver ordering is fixed:
- Backtest uses existing HistoricalReplay order: (timestamp, observation.sequence, str(instrument)).
- Paper rehearsal MUST prevalidate nondecreasing event timestamps before consuming the single-use session or executing any step; regressing inputs are rejected without side effects.
- Within an equal-timestamp rehearsal cohort, caller tuple order is the stable order; do not silently reorder. Cross-driver parity fixtures must supply matching normalized event order.
- Timer snapshots see none of the due cohort's observations. A market callback sees the prior committed engine state plus evidence observed earlier in its driver's fixed order and its own supplied current-frame mark; current-step execution effects are not yet present.

For every timer callback, event is None, as_of equals due_at, and the callback receives the fired TimerInvocation. Timer state/history may contain only evidence available strictly before due_at. No mark or other evidence first observed at or after due_at, and no bar at the timer timestamp, may leak into the snapshot.

Timers advance only when replay/event time advances. Timers beyond the final known input horizon are reported pending/undelivered with a reason; the engine does not invent a run-end timestamp or drain future timers by assumption.

## 5. G2 — commit boundary and callback failures

### 5.1 Pre-commit failures

A failure in on_timer or while building/validating the pre-execution strategy step is recorded and blocks the affected step before intent preparation/execution. The run continues to later eligible input steps; pre-commit failures do not set the post-commit halt latch.

All timers already due before cohort T are attempted in deterministic order even if one fails. Every failure is recorded. If any due timer fails, the entire timestamp cohort T is blocked because its strategy decisions would follow an incomplete pre-frame callback phase. The failed timer is consumed exactly once, not automatically retried; the next strictly later timestamp cohort may proceed. Strategy-local state mutations are not rolled back.

### 5.2 Commit and notifications

A step is committed only after the normalized execution outcome/receipt is recorded and its authoritative fills have been applied exactly once to canonical accounting/account-state paths. An authoritative accepted/submitted-without-fill result is still a committed order-status outcome.

For a committed order-producing step, notify in this order:
1. on_fill once per committed fill in canonical receipt fill order;
2. on_order_update once with the resulting canonical order-status update, including accepted/submitted-without-fill, IOC-cancel, and terminal outcomes.

Every notification in the current committed batch is attempted even if an earlier callback raises. Record all callback errors in deterministic delivery order. Errors never rewrite disposition, remove receipts, erase fills, change committed status, or roll back accounting/portfolio facts. No callbacks fire for no-order/no-fill steps such as NO_ACTION or pre-order risk/policy rejection.

Each callback in a batch receives the same post-commit snapshot for the whole step, not a per-fill historical micro-snapshot. For a market step at T, callback context as_of is T and is never advanced to the maximum receipt/fill timestamp.

**Event-time support boundary:** this first callback-enabled vertical adds no execution-event scheduler. QX-08 paper/backtest runs MUST be preflighted before the first strategy or execution step and MUST reject configurations that can produce receipt/status/fill effective timestamps later than the current driver event time. With the current simulated paper engines, configured nonzero order-to-fill latency is unsupported while QX-08 callbacks/timers are enabled. Unknown/custom executor configurations must declare event-time-coherent support through typed EventTimeSupport (NEW: SUPPORTED, UNSUPPORTED, UNKNOWN); missing/UNKNOWN support fails closed. This restriction applies to callback-enabled QX-08 drivers only, not the general-purpose paper executor. Support for future-effective execution events requires separate event-time execution integration and is out of scope.

The normalized adapter preserves both evidence availability time (when the driver received/committed it) and effective/execution time (receipt executed_at, fill filled_at, or status evidence time); neither can be substituted for the other. In a supported run, committed receipt/status/fill effective times are at or before commit logical time. If a future-effective fact unexpectedly appears despite preflight, preserve the receipt, fills, disposition and canonical ledger facts; mark affected snapshot dimensions incomplete with a temporal-coherence reason; record a separate temporal-integrity fault; and halt before further strategy evaluation/execution. Do not deliver a callback with a falsely coherent snapshot or advance the clock to hide the violation. This exceptional temporal-integrity halt is separate from strategy callback errors and takes precedence over normal notification delivery when a coherent snapshot cannot be built. Timer filtering excludes evidence first available at or after due_at and never uses future market marks. Account valuation is incomplete when canonical tracking cannot derive a coherent value. Ambient time is never used.

### 5.3 Post-commit halt latch

After the full committed notification batch has been attempted, any post-commit callback error sets a run-level halt latch. The committed step remains intact. Ordered callback errors and halt reason are recorded separately from execution facts. No further strategy evaluation, timer callbacks, order callbacks, preparation, or execution occur in that run; remaining timers are recorded undelivered. Callback-error records have stable fields (callback name, invocation/order/fill identity, exception type, deterministic message), without wall-clock or nondeterministic stack text.

Rehearsal and backtest implement equivalent semantics, including accepted-without-fill. The temporal-integrity halt in §5.2 is a separate exceptional path.

## 6. G3 — shared engine-state projection

EngineEvidenceAdapter (NEW) normalizes driver evidence only; build_engine_snapshot() (NEW) is the single shared immutable projection to EngineStateSnapshot. Paper rehearsal and backtest must produce identical snapshot semantics for equivalent normalized evidence.

Reuse existing canonical responsibilities:
- FillAccounting for fill-derived positions and idempotency;
- OrderLifecycle / TERMINAL_ORDER_STATUSES for order-status truth;
- HistoricalAccountStateTracker for supported time-indexed account facts/valuation;
- canonical receipts/fills and paper execution outcomes;
- existing PositionLedger.position_for / PortfolioSnapshot read-view patterns;
- SimulatedClock, HistoricalReplay, registry/compiler/IR and existing risk/policy engines.

The adapter/inventory layer may retain active order identities and canonical status facts across steps, but may not duplicate lifecycle transition validation or accounting. Keep execution/order_lifecycle.py and execution/receipts/lifecycle.py distinct; do not merge or recreate either.

Maintain active/unresolved orders across steps keyed by client_order_id. Never derive the entire open-order inventory from only the latest receipt. Remove an entry only on canonical terminal-status evidence. UNKNOWN, missing, conflicting or non-authoritative status is not terminal and cannot make an order disappear; retain the identity as unresolved/incomplete with a reason.

Position facts are engine-owned and fill-derived. Order facts derive from canonical receipt/status/outcome evidence. Account facts derive only from supported tracker/account evidence. Construction-time AccountFinancialState used to prepare an order is not current account/portfolio state. Missing/stale/untrustworthy evidence is explicit unavailable/incomplete; never manufacture position, fill, order status, marks, cash, market value, equity, or complete valuation. Known-empty inventory is meaningful only when availability/completeness says it is known.

Callback state cuts:
- Timer at due_at: snapshot from evidence available strictly before due_at; nothing from the due cohort is incorporated.
- Market callback at T: current event has been observed and its own supplied mark may be used at T; position/order state is pre-execution for this frame.
- Post-commit callbacks: current step outcome/fills are committed and visible in the post-commit snapshot at as_of T, subject to the event-time support boundary.

as_of is a logical information cut; it does not claim every evidence stream is complete through that time. Per-fact effective timestamps and availability reasons remain explicit. If the canonical tracker cannot build a coherent point-in-time valuation without later marks, the adapter marks account valuation incomplete instead of leaking those marks.

## 7. History

History is strictly prior and same-instrument:
- on_market_data at T admits only bars with observation_time < T;
- on_timer at due_at admits only bars with observation_time < due_at from the TimerInvocation instrument;
- no other instrument or current event/bar is duplicated in history;
- results are ordered by (observation_time, stable sequence), returning the most recent history_bars bars.
The default is 0; cap is 512; invalid inputs fail closed as in §3.

## 8. BuyAndHold (engine-derived, no private position truth)

Remove BuyAndHoldStrategy._entered. From the current engine snapshot for the event instrument:
1. If position or order inventory is unavailable/incomplete, HOLD with no intent and an explicit reason.
2. If a nonzero engine position exists, HOLD.
3. If an active or unresolved order exists, HOLD.
4. Otherwise, emit the normal BUY intent for that evaluation.

This is a state-based entry rule, not a lifetime exactly-once attempt rule. If an entry order becomes canonically terminal with no position, BUY may be retried on a later market event. A risk/policy rejection that creates no order creates no hidden entry-attempt state. A lifetime once-only ledger would be a separate engine-owned fact and is out of scope.

## 9. Acceptance matrix (proposed names, not existing test claims)

- T1 — post-fill paper/backtest position; order inventory persists: test_post_fill_position_is_visible_in_next_context_paper_and_backtest; test_on_fill_receives_postcommit_position_snapshot; test_active_order_persists_until_canonical_terminal_evidence; test_unknown_order_status_does_not_remove_active_order.
- T2 — BuyAndHold state-derived: test_buy_and_hold_holds_for_existing_position; test_buy_and_hold_holds_for_active_or_unknown_order; test_buy_and_hold_holds_when_position_or_order_inventory_is_incomplete; test_buy_and_hold_retries_after_terminal_entry_without_position.
- T3 — parity: test_paper_and_backtest_share_engine_snapshot_semantics; test_paper_and_backtest_order_sequence_parity; test_accepted_without_fill_notification_parity.
- T4 — timers/callback phases/errors/immutability: test_timer_request_rejects_equal_or_past_due_at; test_timer_dispatch_orders_by_due_at_then_timer_id; test_timer_dispatch_precedes_entire_equal_timestamp_cohort; test_timer_context_exposes_due_timer_and_as_of; test_timer_history_is_prior_only_and_same_instrument; test_timer_snapshot_excludes_future_and_same_timestamp_cohort_evidence; test_timer_after_replay_horizon_is_reported_pending; test_rehearsal_rejects_regressing_input_timestamps_before_consuming_session; test_rehearsal_preserves_caller_order_within_timestamp_cohort; test_callback_driver_rejects_nonzero_execution_latency_before_first_step; test_unknown_executor_time_capability_fails_closed; test_unexpected_future_effective_receipt_preserves_facts_and_halts_without_false_snapshot; test_receipt_and_fill_keep_availability_and_effective_times_distinct; test_precommit_timer_failure_blocks_current_cohort_and_run_continues; test_postcommit_callback_errors_complete_batch_then_latch_halt; test_multiple_callback_errors_are_recorded_in_delivery_order; test_accepted_without_fill_is_preserved_after_order_callback_error; test_context_views_are_deeply_immutable.
- T5 — incomplete/stale evidence: test_missing_position_order_and_account_evidence_has_explicit_reason; test_stale_mark_makes_valuation_incomplete; test_snapshot_never_uses_starting_financial_state_as_current_account.
- T6 — behavioral no-broker/no-LIVE and PAPER-only: test_strategy_context_callbacks_have_no_broker_submit_capability plus existing non-PAPER deployment rejection tests.
- T7 — repeatability: test_repeated_strategy_run_has_identical_decisions_notifications_and_halt_records.
- T8 — standalone static/AST boundary: test_strategy_seams_have_no_broker_or_live_path checks an explicit seam-file set, forbidden imports/capabilities/call targets, wall-clock/scheduler use, and direct LIVE/broker-submit references. Expanding the seam-file set requires an explicit test change. This is a structural regression check, not a proof against arbitrary Python reflection.

Cross-cut requirements:
- G2 pre-commit blocking, due-timer batch completion, committed-outcome preservation, notification completion, halt timing, and accepted-without-fill are explicit T4/T3 cases.
- G3 active-order identity/persistence/terminal removal, UNKNOWN status, known-empty vs incomplete inventories, and valuation unavailability are explicit T1/T5 cases.
- Parameter tests cover canonical lexical forms, missing/default values, malformed integer/Decimal, uppercase/other boolean lexemes, whitespace, plus signs, leading zeros, exponent/non-finite Decimal, negatives, 512 and 513, including field-named errors.
- Every test asserts outcome and preserved evidence, not merely method invocation or exception occurrence.

## 10. M1–M4 implementation map

- M1 — context, snapshots, adapters, EventTimeSupport preflight, frozen view types, typed params/history: T1 foundations, T5, immutability/history tests, and T8.
- M2 — callbacks, timer request validation, event-time due list, timer identity/context, timestamp cohorts and G1/G2 error/halt semantics: T4 and T8 checkpoint.
- M3 — context-derived BuyAndHold and strict typed params/history bounds: T2 and parameter/history boundary tests.
- M4 — paper/backtest driver wiring and parity, preserving existing risk/policy/execution behavior: T1/T3/T7 and T6/T8 checkpoints.

A phase is complete only when its mapped tests exist and pass at the exact reviewed commit, with focused regressions, full local pytest, changed-file Ruff/format, strict mypy where applicable, and git diff --check. GitHub Actions is disabled by project policy; no Actions evidence is expected or claimed.

## 11. Reuse and exclusions

No risk redesign, execution/recovery redesign, new runtime, second event bus, second accounting system, second lifecycle reducer, persistence redesign, Flow UI/parity implementation, execution-event scheduler, external scheduling infrastructure, AI/agents, broker-matrix expansion, or LIVE strategy execution. No real broker order is in scope. The nonzero-latency callback restriction in §5.2 is specific to QX-08's first vertical.

## 12. Gate decision

**Design-gate PASS after this brief and the synchronized canonical docs merge together.** G1/G2/G3/T8, timer identities/ordering/end-of-stream, callback failure/commit semantics, event-time limits, shared state availability, BuyAndHold retry semantics, strict prior history, typed parameter grammar and the complete T1–T8/M1–M4 traceability are normative here. This is not implementation validation. Implementation remains the next gated task; each phase must pass its mapped tests at the exact reviewed SHA.
