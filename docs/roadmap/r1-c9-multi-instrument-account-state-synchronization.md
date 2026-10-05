# R1-C9 Multi-Instrument Account-State Synchronization

**Implementation status:** implementation complete on `feat/r1c9-multi-instrument-account-state-synchronization`; external OpenCode validation is required before merge.

## Goal

Define deterministic time-indexed historical account-state sampling for portfolios with multiple open-position instruments whose market observations occur on different replay frames.

C7 uses exact-current marks for time-indexed samples. That correctly prevents stale valuation, but interleaved multi-instrument replay can make a portfolio sample INCOMPLETE when only one instrument has a current-frame observation.

C9 defines the synchronization policy explicitly.

## Scope

C9 is limited to the existing historical account-state sampling path:

`HistoricalReplay -> HistoricalAccountStateTracker -> account_state_series`

Introduce an explicit sampling policy in the backtest application boundary, mapped onto the existing tracker behavior.

Supported policies:

- **EXACT_CURRENT:** every open position requires a mark observed exactly at the sample timestamp.
- **AS_OF_OBSERVED:** every open position may use its latest explicit mark observed at or before the sample timestamp; future marks are never eligible.

AS_OF_OBSERVED does not claim that a mark is current. R1-C8 provenance remains the evidence surface showing `observed_at` and `selected_at`.

## Determinism

For a given replay and policy:

- no wall-clock access;
- no future observations;
- no implicit price fallback;
- no broker/network reads;
- no float financial calculations;
- identical input and policy produce identical state-series results.

Policy selection should be explicit in the backtest configuration/result only where an existing result boundary can hold it cleanly. Do not introduce unrelated experiment infrastructure.

## Fail-closed rules

EXACT_CURRENT:
- missing mark -> INCOMPLETE;
- future mark -> INCOMPLETE;
- older mark -> INCOMPLETE;
- unusable mark -> INCOMPLETE.

AS_OF_OBSERVED:
- missing mark -> INCOMPLETE;
- future mark -> INCOMPLETE;
- latest explicit mark at or before the timestamp -> usable;
- mark age remains visible through C8 provenance.

Neither policy may use a future mark or convert missing evidence to zero.

## Backtest semantics

For each replay frame:

1. observe the frame's explicit market mark;
2. sample account state under the configured policy;
3. run strategy/risk/policy/execution;
4. record any receipt-driven C4 account state after execution.

The current frame's execution result must not enter that frame's series sample.

## Compatibility

- C4 receipt-driven `account_states` semantics remain unchanged.
- C7 EXACT_CURRENT behavior remains the default unless existing configuration semantics require another explicit default.
- The new policy is additive and explicit.
- The derived series remains outside pre-trade risk.
- No duplicate accounting/P&L path.

## Validation

Focused tests must cover:

- one-instrument EXACT_CURRENT behavior;
- interleaved multi-instrument replay becoming INCOMPLETE under EXACT_CURRENT when another open position lacks a current mark;
- the same replay becoming COMPLETE under AS_OF_OBSERVED when prior marks exist for every open position;
- future-only evidence rejected under AS_OF_OBSERVED;
- C8 provenance exposing mark age under AS_OF_OBSERVED;
- deterministic evidence ordering;
- unchanged C4 receipt-driven snapshots;
- unchanged account-state calculations;
- no effect on LIVE, broker, reconciliation, or risk paths.

Then run full pytest, changed-file Ruff, strict mypy for changed production files, and `git diff --check`.

## Deferred

C9 does not add configurable freshness thresholds, margin/buying-power evolution, financing/funding/borrow/tax/FX, new intrabar models, UI/API work, or AI/ML valuation.


## Implemented boundary

The application result now records the selected `AccountStateSamplingPolicy`.

`EXACT_CURRENT` is the default and preserves C7 behavior.

`AS_OF_OBSERVED` reuses the tracker's existing as-of behavior without introducing a second valuation engine. C8 provenance records the observation timestamp separately from the sample timestamp so mark age remains explicit.
