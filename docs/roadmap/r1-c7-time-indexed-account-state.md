# R1-C7 Time-Indexed Account-State Sampling

## Goal

Provide deterministic account-state samples at replay-frame timestamps independently of whether a strategy executes an order on that frame.

C7 is a research/backtest projection only. It does not replace the existing receipt-driven C4 account-state snapshots and does not feed derived state back into pre-trade risk.

## Design

The canonical tracker remains:

`HistoricalAccountStateTracker`

The tracker gains timestamped mark evidence and an additive `snapshot_at(..., require_current_marks=True)` operation.

The backtest result gains:

`account_state_series: tuple[HistoricalAccountStateSnapshot, ...]`

This series contains one sample per replay frame and is taken after the frame's explicit market mark is observed, but before strategy/risk/execution effects for that frame.

## Mark semantics

Every mark created from a historical observation retains the observation timestamp.

For ordinary receipt-driven C4 snapshots, the tracker may use the latest explicit mark that is not in the future relative to the state timestamp. This preserves the existing event-state behavior when simulated execution latency moves the receipt timestamp after the observed market timestamp.

For C7 time-indexed samples, every open position must have an explicit mark observed at exactly the sample timestamp. An older mark is not reused as current evidence. Missing or unusable current marks produce an INCOMPLETE snapshot with explicit unavailable-instrument evidence.

## Compatibility

The existing `account_states` field remains receipt-driven and unchanged in meaning.

The new `account_state_series` field is additive. It is not a second accounting engine; it is another immutable projection of the same `FillAccounting` + `CashLedger` state maintained by C4.

## Determinism and safety

- Decimal-only financial calculations remain unchanged.
- No broker or network dependency is introduced.
- No LIVE execution semantics change.
- No risk decision consumes the derived series.
- No stale mark is silently promoted to current evidence in the time-indexed series.
- The current frame's execution result is not included in that frame's sample.

## Validation

Focused tracker, valuation, and backtest tests plus the full suite, changed-file Ruff, strict mypy for changed production files, and `git diff --check` are required before merge.
