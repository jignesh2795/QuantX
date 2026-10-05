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
```

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

The tracker retains the most recent explicit mark for an instrument when later account events occur. The state remains incomplete when an open position has no retained mark.

## Capital boundary

Only PAPER_CONFIGURED and BACKTEST_CONFIGURED starting capital are accepted by this historical tracker. LIVE_BROKER state is rejected because a historical account trajectory cannot derive broker-observed state from a configured replay ledger.

Margin, leverage, buying-power formulas, and broker-specific capital rules are intentionally not evolved by C4. The existing caller-supplied AccountFinancialState remains the input to risk evaluation.

## Backtest integration

DeterministicBacktestService exposes one post-event account-state snapshot for each execution receipt.

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

- time-indexed snapshots independent of execution events;
- explicit margin-reservation evolution;
- broker-observed account-state reconciliation;
- account-level market data and FX conversion;
- daily P&L/financing/tax state when authoritative rules are available.

These remain separate from C4.
