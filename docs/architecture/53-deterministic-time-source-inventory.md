# Deterministic Time-Source Inventory (Issue #179)

Audited against `main` at `98bc640c5af68633d573b701542f982dab462ea3` plus the
Issue #179 branch head; line numbers below track the branch head. Search
method: every `datetime.now`, `utcnow`/`utc_now`, timestamp
`default_factory`, `time.time`/`monotonic`, and `Clock`/`SystemClock`/
`FixedClock`/`SimulatedClock` construction site under `src/quantx/`.
Result: **38 direct `datetime.now` calls** (reconciling the issue's count),
4 wall-clock default factories, and the `Clock` definitions plus injection
sites. No `time.time`, `monotonic`, or `utcnow` uses exist in `src/`.

Classification: **replay/event time** (must come from market/replay
evidence), **injected operation time** (must come from a `Clock`), or
**intentional wall-clock/transport/operational time** (legitimate real-time
use; never replay evidence).

## Remediated replay-path sites

- `application/backtest.py:800` — `created_at=frame.observation.timestamp`:
  every backtest order carries the explicit replay occurrence time, on the
  default and the caller-supplied engine path. Replay/event time.
- `application/backtest.py:493` — `_require_engine_time_coherent`
  preflight: reads the injected engine clock before executing and rejects
  a clock behind the replay frame, so a rejected run records no
  idempotency reservation/completion, no receipt write, no retained
  receipt, and no lifecycle events.
- `application/backtest.py:471` — `_require_coherent_execution_time`
  backstop: retained alongside preflight for a clock that moves between
  validation and execution. A receipt or fill stamped before order
  creation aborts the run instead of recording contradictory evidence.
- `application/backtest.py:453` — signal timestamp guard (pre-existing):
  any signal whose `generated_at` differs from the replay frame is rejected.
- `application/backtest.py:558` — `clock=simulation_clock`: the service-owned
  venue clock, advanced per frame. Injected operation time.
- `execution/paper_engine.py:85` — read-only `clock` property exposing the
  injected time authority for preflight checks; the engine never rewrites it.

## Replay/event time (explicit; no wall clock)

- `research/replay.py:159` — `ReplayFrame` passthrough of
  `observation.timestamp`; merge sorted by `(timestamp, sequence)`.
- `research/event_replay.py:25,43` — `ReplayEvent.timestamp`,
  `ReplayEventContext.as_of`: explicit required, timezone-guarded.
- `research/lifecycle.py` — `valid_from/valid_to/effective_at/listed_from/
  expiry_at/settled_at`: explicit, timezone-guarded.
- `research/result.py:95-98` — `started_at/completed_at/time_range_start/
  time_range_end`: explicit required strings, no defaults.
- `application/backtest.py:610` — `BacktestStep.timestamp` from
  `frame.observation.timestamp`.
- `execution/historical_account_state.py:192,241` — marks from
  `snapshot.timestamp`; snapshots from `receipt.executed_at`.
- `execution/paper/executor.py:95` — fills from caller-supplied
  `fill_at_ns`; `paper/broker.py:69,86`, `paper/profile.py:68` — nanosecond
  passthrough, no internal wall read.
- `execution/paper_session.py:186,429` — projected fills from
  `snapshot.timestamp`.
- `strategy/reference.py:32,45,76,90,109` — reference strategies bind
  `generated_at=event.timestamp`.
- `strategy/evaluation.py:44,60` — replay-frame event construction.
- `application/research_backtest.py:122-123` — `time_range_*` from first/last
  step timestamps.

## Injected operation time (caller-owned `Clock`)

- `execution/paper_engine.py:126,169` — receipts, fills, and lifecycle
  events from `self._clock.now()` (`SimulatedClock` on the default backtest
  path; caller-owned on injection).
- `application/research_backtest.py:131`,
  `application/research_run.py:77` — run records from the injected clock;
  deterministic under test `FixedClock`s. Fingerprints exclude these
  operation times (`research/result.py:145` derives from spec provenance).
- `plugins/reference_broker/transport.py:87` — deterministic `FixedClock`
  default; wall clock only if a host injects `SystemClock`.
- `domain/sessions.py:63,68` (`TradingSession`) and
  `india/session_calendar.py:144,156` (`IndiaSessionEvaluator`,
  explicitly the LIVE session boundary) — clock-backed session checks on
  LIVE paths only; never reachable from replay/backtest.
- `domain/clock.py:14,23,30,43` — `Clock` port, `SystemClock`,
  `FixedClock`, `SimulatedClock` definitions.

## Intentional wall-clock/transport/operational time (retained)

- `domain/orders.py:10,18` (`utc_now` definition) with field defaults
  `:32` (`Order.created_at`), `:69` (`Fill.filled_at`): interactive/LIVE
  construction default. Replay paths restamp or guard (see remediated
  sites); reachable from replay only through the covered backtest paths.
- `domain/strategy.py:60` (`StrategySignal.generated_at` default):
  interactive default; the backtest guard rejects any replay signal that
  relies on it (regression: `test_backtest_rejects_signal_using_
  wall_clock_default`).
- `research/experiments.py:23` (`Experiment.created_at` default):
  researcher-driven creation; durable reads pass the stored timestamp
  explicitly (`persistence/sqlite/experiments.py:16`), so the default
  cannot leak into replay evidence.
- `plugins/dhan/transport.py:211,243,259,477,486,551,557,568,574,579,591,
  599,606,615,621,669` (16) — live broker observation timestamps.
- `plugins/dhan/adapter.py:179,365` — LIVE-only fallbacks when the broker
  supplies no parseable time, and UNKNOWN receipts. Reachable only via
  LIVE dispatch, never replay/backtest/paper.
- `application/runtime.py:62`, `pending_recovery.py:118`,
  `pending_reconciliation.py:70`, `operator_resolution.py:44` —
  LIVE boot/recovery/operator parameters with explicit overrides.
- `persistence/sqlite/idempotency.py:141,179,206,264`,
  `research.py:108`, `schema.py:236,262,274,285,295,304`,
  `trading_gate.py:43` (12) — row-write bookkeeping times; schema and
  stored values unchanged by this slice.

## Deliberately unchanged (documented, not forced)

- `strategy/execution.py:105` (`StrategyExecutionPreparer` builds orders
  with the wall-clock default): no in-repository callers, so no replay
  path can reach it; adding a clock parameter would be API churn without
  proof. Left unchanged.
- Injected-engine clock ownership: the service never rewrites a
  caller-supplied engine clock; mismatch fails closed instead.
- `research/result.py:102` (`result_id` UUID default): explicitly random
  identity, not time-related; excluded from determinism comparisons.
