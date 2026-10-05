# R1-C8 Account-State Valuation Provenance

**Implementation status:** implementation complete on `feat/r1c8-account-state-valuation-provenance`; external OpenCode validation is required before merge.

## Goal

Make the market evidence supporting a historical account-state snapshot explicitly auditable.

C8 is the smallest deterministic research/account-state gap following C7. C7 established timestamped marks and fail-closed time-indexed sampling; C8 makes the valuation evidence itself visible in the snapshot contract so downstream research can explain exactly what mark was used or why valuation was unavailable.

## Scope

C8 is limited to the existing historical account-state and valuation path:

`HistoricalObservation -> HistoricalAccountStateTracker -> MarkToMarketValuator -> HistoricalAccountStateSnapshot`

The slice implements:

- expose the mark evidence used for each valued open position;
- preserve instrument identity;
- preserve mark source;
- preserve mark observation timestamp;
- distinguish an unavailable mark from a fabricated/default value;
- keep deterministic ordering for multiple position marks;
- retain explicit incompleteness when required valuation evidence is missing;
- reuse the existing `Mark` and `HistoricalAccountStateTracker` boundaries.

No second valuation engine, accounting ledger, or research-state path should be introduced.

## Proposed evidence contract

The exact type/name is an implementation decision after repository inspection, but the resulting snapshot should expose an immutable evidence record with at least:

`instrument_id`
`mark_price` (Decimal or explicit unavailable state)
`source`
`observed_at`
`selection/as-of timestamp` when the distinction matters

The snapshot should make it possible to answer:

1. Which instrument was valued?
2. Which explicit mark supported the valuation?
3. When was that mark observed?
4. What source produced it?
5. Was the mark current at the requested sampling timestamp, or was an as-of mark selected for receipt-driven C4 semantics?
6. Why was valuation withheld when evidence was unavailable?

## C4 compatibility

Existing receipt-driven `account_states` semantics remain unchanged.

C4 may continue using the latest explicit mark not in the future relative to the receipt timestamp. C8 records that evidence rather than changing the selection rule.

The C7 `account_state_series` exact-current-mark rule also remains unchanged. Its evidence should identify the exact current observation used for a complete sample, or preserve an explicit unavailable state for incomplete valuation.

## Determinism

Evidence ordering must be deterministic.

The same replay inputs, execution receipts, and mark set must produce the same snapshot values and the same evidence sequence.

No wall-clock access, broker query, implicit price fallback, float conversion, or unordered externally-derived representation may enter the path.

## Safety boundary

Research/backtest only.

C8 must not alter:

- LIVE execution;
- broker transports or adapters;
- reconciliation;
- retry or resubmission;
- UNKNOWN handling;
- recovery;
- pre-trade risk;
- capital source rules;
- existing FillAccounting/CashLedger behavior.

## Validation

The implementation adds focused coverage. Before merge, external OpenCode validation should prove:

- complete long and short valuation carries explicit mark evidence;
- C4 as-of mark selection is represented correctly;
- C7 exact-current marks are represented correctly;
- missing, future, stale, or unusable marks remain explicitly unavailable/incomplete;
- evidence ordering is deterministic;
- existing `account_states` and `account_state_series` behavior is unchanged;
- no duplicate valuation/accounting path exists.

Then run the full suite, changed-file Ruff, strict mypy for changed production files, and `git diff --check`.

## Explicitly deferred

C8 does not solve:

- multi-instrument synchronization policy;
- margin and buying-power evolution;
- financing, funding, borrow, taxes, or FX;
- broad intrabar/microstructure realism;
- UI/API presentation work;
- AI-generated valuation or execution estimates.

Those remain separate decisions.
