# Execution Realism and Research Provenance

## Execution realism

QuantX must treat execution assumptions as explicit models rather than hidden backtest constants.

Execution models may include:

- simple fill
- bid/ask fill
- spread-aware fill
- bar approximation
- latency-aware fill
- partial-fill model
- queue/market-impact model
- custom venue model

Models should account for applicable:

- tick size
- lot size
- trading session
- price bands/circuit rules
- slippage
- spread
- latency
- partial fills
- order rejection
- expiry behavior
- fees and charges

## Scenario and fault injection

The simulation layer should support controlled scenarios for:

- latency
- stale data
- dropped connections
- duplicate events
- out-of-order events
- order rejection
- partial fills
- market gaps
- broker outage
- delayed acknowledgements

The goal is to test both strategy performance and operational resilience.

## Reproducibility

Every meaningful research result should be traceable to:

- dataset/version
- strategy version
- parameters
- QuantX engine version
- execution model
- commission/charge model
- market calendar version
- random seed, where applicable
- configuration
- plugin versions

## Experiment identity

A backtest or optimization run should produce a durable experiment record containing configuration, metrics, artifacts, and provenance.

Conceptually:

```text
Experiment
  -> Dataset
  -> Strategy
  -> Parameters
  -> Engine
  -> Execution model
  -> Results
  -> Artifacts
```

## Strategy promotion

A strategy should progress through explicit states rather than jumping directly from creation to live execution:

```text
DRAFT
  -> VALIDATED
  -> BACKTESTED
  -> ROBUSTNESS_CHECKED
  -> PAPER
  -> APPROVED
  -> LIVE
  -> PAUSED / RETIRED
```

Promotion criteria are configurable and may include out-of-sample performance, drawdown limits, robustness results, paper-trading observation, and approval policy.

## Corporate actions

Equity research and portfolio accounting must model or explicitly account for dividends, splits, bonus issues, rights issues, mergers, demergers, symbol changes, and other applicable corporate actions.

## Market calendar

The calendar subsystem must represent normal sessions and special sessions rather than relying on hard-coded trading hours. It should support holidays, pre-open/auction sessions, regular sessions, post-market behavior, and derivatives expiry/session rules where applicable.