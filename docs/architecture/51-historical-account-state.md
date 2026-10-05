# Historical Account-State Evolution

## Purpose

R1-C4 adds a deterministic account-state seam for historical replay and backtests.

The seam derives simulated state from:

- explicitly configured starting capital;
- canonical simulated execution receipts and fills;
- modeled execution fees;
- existing deterministic position accounting;
- explicitly supplied historical market marks.

It never queries a broker and never treats simulated state as historical broker truth.

## State contract

Each account-state snapshot records:

```
timestamp
capital source
cash
signed market value
equity
realized P&L
unrealized P&L
gross exposure
modeled fees
position ledger
completeness
unavailable instruments / explicit issue
valuation evidence
```

Valuation evidence is an immutable, deterministic sequence containing the
instrument identity, explicit mark price when available, mark source, mark
observation timestamp, snapshot selection timestamp, availability state, and
an explicit reason when the evidence is unavailable. This makes both ordinary
C4 as-of valuation and C7 exact-current sampling auditable without changing
their selection rules.

COMPLETE means the configured cash state and every open position have an explicit valuation mark.

INCOMPLETE means required evidence is unavailable. Valuation fields are withheld rather than partially aggregated or fabricated.

## Valuation semantics

Market value is signed:

```
long position  -> positive market value
short position -> negative market value
```

This keeps:

```
equity = cash + signed market value
```

consistent at trade entry for both long and short positions.

Gross exposure remains unsigned.

Realized P&L comes from the existing FillAccounting ledger. Fees are recorded separately and are already reflected in the cash ledger.

## Mark evidence

For each supplied historical observation:

- candle close is an explicit bar mark;
- quote last is preferred when present;
- quote bid/ask midpoint is used only when both are explicitly present.

No price is inferred from unrelated data.

Marks now carry their explicit observation timestamp. Receipt-driven account-state snapshots may use the latest known mark that is not in the future relative to the snapshot timestamp, preserving the existing latency-aware event-state behavior. Time-indexed research samples default to an exact-current-mark policy and therefore do not reuse an older mark as though it were current; an explicit AS_OF_OBSERVED sampling policy may instead reuse the latest mark at or before the sample timestamp, with its age exposed through valuation evidence. Missing or future evidence remains incomplete.

## Capital boundary

Only PAPER_CONFIGURED and BACKTEST_CONFIGURED starting capital are accepted by this historical tracker. LIVE_BROKER state is rejected because a historical account trajectory cannot derive broker-observed state from a configured replay ledger.

Margin, leverage, buying-power formulas, and broker-specific capital rules are intentionally not evolved by C4. The existing caller-supplied AccountFinancialState remains the input to risk evaluation.

## Backtest integration

DeterministicBacktestService retains one post-event account-state snapshot for each execution receipt and now also exposes a separate time-indexed account-state series with one sample per replay frame. The series is sampled after the frame's explicit market mark is observed but before that frame's strategy/risk/execution effects, so a sample cannot include the current frame's future execution result. Existing receipt-driven snapshots remain unchanged.

The existing strategy, risk, policy, execution, and position-accounting semantics remain unchanged. C4 does not feed the derived account-state trajectory back into pre-trade risk in this slice.

```
Historical data
  ↓
Strategy
  ↓
Risk / policy
  ↓
Paper execution
  ↓
FillAccounting + CashLedger
  ↓
HistoricalAccountStateSnapshot
```

## Valuation evidence provenance

For each open position, the tracker records the explicit mark considered at
the snapshot boundary. A complete evidence record identifies the mark that was
actually used for valuation. An unavailable record preserves the explicit mark
metadata when present and states why it could not be used, including missing
marks, future observations, unusable prices, or stale marks under exact-current
sampling.

Evidence is emitted in the same deterministic position order used by the
snapshot and carries the requested snapshot timestamp separately from the
mark observation timestamp. Therefore a receipt-driven C4 snapshot can expose
that an as-of mark observed earlier was selected at a later receipt timestamp,
while a C7 series sample can prove that its mark was observed exactly at the
sample timestamp.

## Safety boundary

This is a deterministic simulation/research state boundary.

It does not:

- call broker APIs;
- submit real orders;
- alter LIVE risk limits;
- infer missing margin/leverage rules;
- invent marks;
- convert unavailable valuation evidence into zero.

## Future work

Later account-state slices may add:

- explicit margin-reservation evolution;
- broker-observed account-state reconciliation;
- account-level market data and FX conversion;
- daily P&L/financing/tax state when authoritative rules are available.

These remain separate from C4.
