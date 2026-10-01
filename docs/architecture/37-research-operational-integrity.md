# Research and Operational Integrity

## Purpose

QuantX should produce results that are not only plausible but auditable, reproducible, and operationally faithful.

This document adds the remaining integrity rules around historical research, simulation, live/paper parity, and runtime operation.

## 1. Point-in-time universe

Historical research must use the universe that was actually eligible at the simulated time.

The system must avoid survivorship bias from using today's symbols, constituents, contracts, or instruments for past periods.

Record:

```text
UniverseId
UniverseVersion
EffectiveFrom
EffectiveTo
MembershipSource
```

For equities and indices, delisted or removed instruments must remain representable in historical datasets when the source supports them.

## 2. Point-in-time metadata

Instrument, contract, broker capability, fee, margin, trading-calendar, and symbol-mapping information must be selected using an effective timestamp.

Do not silently apply today's metadata to historical periods.

```text
EventTime
    ↓
Effective metadata version
    ↓
Simulation
```

## 3. Trading calendars and session state

Market open/close state must be modeled explicitly.

Support:

- venue holidays;
- special sessions;
- auctions;
- pre-open/post-close sessions;
- daylight-saving effects where applicable;
- exchange timezone;
- instrument-specific trading windows;
- expiry/settlement windows.

UTC timestamps are required for event storage, but simulation must preserve the relevant venue-local timezone and session identity.

## 4. Data-quality gates

Historical and live data should pass explicit quality checks before entering research or execution models.

Examples:

```text
missing timestamps
duplicate records
out-of-order records
invalid OHLC relationships
negative/zero impossible prices
negative volume where not supported
crossed or invalid quotes
unexpected corporate-action jumps
contract metadata conflicts
```

Each dataset receives a machine-readable quality status.

```text
VALID
VALID_WITH_WARNINGS
DEGRADED
REJECTED
```

A run may be blocked when the selected strategy/model requires data quality that the dataset does not meet.

## 5. Transaction-cost integrity

Backtests and paper execution should model the costs applicable to the selected market and account context rather than one universal fee assumption.

Separate:

```text
BrokerFees
ExchangeFees
Taxes
RegulatoryCharges
Funding
BorrowCosts
Slippage
MarketImpact
```

The cost model must be versioned and time-aware.

## 6. Funding and carry

Where relevant, simulations must explicitly model funding, borrow, financing, dividends, and carry.

Unavailable costs must not be silently treated as zero when they materially affect the experiment.

## 7. Deterministic stochastic simulation

If simulation uses randomness, every run must support reproducibility.

Record:

```text
RandomSeed
RandomAlgorithm
SimulationModelVersion
```

The same dataset, configuration, model version, and seed should reproduce the same result unless the execution engine explicitly declares nondeterminism.

## 8. No hidden execution assumptions

Every simulation profile must explicitly state how it handles:

```text
market orders
limit orders
stop orders
partial fills
gaps
latency
spread
slippage
liquidity
order cancellation
rejections
session boundaries
```

A default may exist for usability, but it must be visible and recorded in the run provenance.

## 9. No silent look-ahead through feature pipelines

Look-ahead prevention applies not only to raw data but also to feature engineering, normalization, scaling, label creation, hyperparameter selection, and model training.

Examples of prohibited leakage:

```text
fit scaler on future period
use full-dataset normalization before time split
select features using future labels
train on data later than the simulated decision timestamp
use future corporate-action knowledge when unavailable at the time
```

Training and inference must have explicit causal cutoffs.

## 10. Walk-forward evaluation

Strategy and ML evaluation should support chronological evaluation such as:

```text
TRAIN → VALIDATE → TEST
       ↓
     advance
       ↓
TRAIN → VALIDATE → TEST
```

A model should not be considered validated merely because it performs well on the same period used for tuning.

## 11. Benchmark and attribution

Performance reports should distinguish strategy alpha from market movement and execution effects where possible.

Record benchmarks appropriate to the market/context and calculate attribution such as:

```text
Gross P&L
- Transaction Costs
- Funding/Carry
= Net P&L

Signal contribution
Execution contribution
Allocation contribution
Market/benchmark contribution
```

## 12. Result immutability

A completed historical/backtest result should behave like an immutable research artifact.

If source data, rules, configuration, strategy version, or simulation code changes, create a new run rather than silently modifying the old result.

Every run receives a stable `RunId` and provenance fingerprint.

## 13. Paper/live parity tests

QuantX should periodically run contract tests that execute the same approved request through:

```text
Paper adapter
Live adapter mock
Broker adapter test harness
```

The objective is to detect semantic drift in:

- order normalization;
- order status transitions;
- quantity/lot handling;
- price handling;
- cancellation;
- partial fills;
- rejection mapping;
- fee accounting.

## 14. Failure injection

Execution infrastructure should support controlled failure tests for:

```text
broker timeout
network disconnect
duplicate response
stale quote
partial response
order acknowledgement loss
websocket reconnect
rate limit
credential expiry
inconsistent broker state
```

This should be available in paper/test environments before live deployment.

## 15. Reconciliation as a first-class process

The external broker state and local QuantX state must be reconcilable at any time.

At minimum compare:

```text
orders
fills
positions
cash
margin
open orders
external order identifiers
```

Differences should produce explicit reconciliation events and must not be silently overwritten.

## 16. Operational observability

Every execution path should expose structured telemetry for:

```text
latency
order lifecycle duration
fill latency
rejections
reconnects
risk decisions
routing decisions
reconciliation differences
simulation fidelity
```

Logs should carry correlation and causation identifiers so one user action or strategy intent can be traced through the entire system.

## 17. Security boundaries

Credentials and secrets must remain outside the universal domain model.

Plugins, strategies, AI agents, and UI components receive scoped capabilities rather than raw credentials.

Live execution should require explicit environment/account permission and should not be enabled merely by changing a UI toggle.

## 18. Safe degradation

When data, broker connectivity, or a required capability becomes unavailable, the system should prefer a declared safe state over silently substituting an assumption.

Possible states include:

```text
READ_ONLY
SAFE_MODE
PAUSED
DEGRADED
REQUIRES_RECONCILIATION
```

## 19. Research-to-live promotion

A strategy should move toward live execution through explicit stages:

```text
Research
  ↓
Backtest
  ↓
Walk-forward
  ↓
Replay
  ↓
Shadow
  ↓
Paper
  ↓
Approval
  ↓
Live
```

Each promotion should retain the strategy version, configuration, risk policy, and evidence used for the decision.

## 20. Final integrity principle

QuantX must prefer:

```text
accurate + incomplete
```

over:

```text
complete-looking + unsupported
```

The same rule applies to data, historical results, paper fills, broker state, AI explanations, and dashboards.
