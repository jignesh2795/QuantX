# Paper Execution Realism

## Goal

QuantX paper/simulation execution should be as close to real execution as the available market data and declared simulation model allow. Paper mode is not intended to be an idealized backtest with guaranteed fills.

## Core rule

Paper execution must model the same execution path used by live trading:

```text
Strategy
  -> TradeIntent
  -> allocation / constraints / risk
  -> routing
  -> ApprovedExecutionRequest
  -> ExecutionPort
  -> simulated venue model
  -> fills / order events
```

Only the final venue interaction is simulated.

## Fidelity layers

The simulator should be capability-driven and progressively configurable:

1. **Market price source** — last trade, bid/ask, OHLCV, or depth when available.
2. **Spread** — buy orders interact with ask-side pricing and sells with bid-side pricing when bid/ask data exists.
3. **Slippage** — configurable deterministic or data-driven model.
4. **Latency** — configurable decision-to-submit and submit-to-fill delay.
5. **Partial fills** — supported when order size, depth, or simulation rules require them.
6. **Order type semantics** — market, limit, stop and stop-limit behavior must differ.
7. **Trading sessions** — market calendar/session state controls whether an order can execute.
8. **Fees and taxes** — venue/broker cost models are applied explicitly rather than hidden in strategy returns.
9. **Rejects** — unavailable liquidity, invalid order parameters, closed sessions, broker constraints, and other declared failures can reject an order.
10. **Reconnect/replay behavior** — event order and timing should remain deterministic under replay.

## Fidelity profiles

Simulation must expose a named profile instead of one universal behavior:

- `BASIC` — deterministic bar-level simulation.
- `REALISTIC` — bid/ask, spread, fees, slippage, latency, partial-fill and order-type modeling when supported by data.
- `MICROSTRUCTURE` — depth/queue/impact modeling where sufficiently rich data exists.
- `CUSTOM` — explicitly configured model components.

The default profile must not claim realism that the available data cannot support.

## Data-adaptive simulation

The simulator should inspect available data capabilities:

```text
OHLCV only
  -> bar-based model

Bid/ask available
  -> spread-aware model

Trade + quote stream
  -> quote/trade interaction

Depth/order-book available
  -> depth-aware model
```

When required data is unavailable, QuantX must downgrade the model explicitly and record the downgrade in the simulation provenance.

## AI-assisted realism

An AI/ML model may later select or calibrate simulation parameters from real market data, but it must remain optional and replaceable.

```text
Real market data
    -> feature/statistics extraction
    -> optional AI model
    -> simulation parameters/model choice
    -> simulator
```

The AI model must not silently change execution semantics or bypass deterministic safety rules. Its selected model, inputs, version and outputs should be included in experiment provenance.

## Realism versus determinism

Every simulation must identify whether results are deterministic. A stochastic model must use an explicit seed or reproducible random-state specification for replayable experiments.

## Live/paper parity

The following should remain shared between paper and live paths:

- TradeIntent semantics
- risk and constraints
- capital/account context
- routing decisions
- order lifecycle state machine
- idempotency rules
- execution events and audit identifiers

The paper adapter may replace only the external venue interaction and market-fill model.

## No fake certainty

The simulator must never report a fill merely because an order was requested. Fill probability and fill price must be derived from the selected simulation model and available data.

Simulation results should expose:

- requested quantity
- filled quantity
- unfilled quantity
- simulated fill prices
- fees/costs
- assumed latency
- slippage
- data source
- fidelity profile
- model version
- random seed when applicable

## Future AI extension

A future AI execution model can estimate:

- fill probability
- expected slippage
- market impact
- latency effects
- queue position
- adverse selection

but these remain **simulation/model outputs**, not broker truth.
