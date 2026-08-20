# Execution Environments and Replay

Status: Draft

## Four first-class environments

```text
BACKTEST
REPLAY
SANDBOX / PAPER
LIVE
```

The application code and domain semantics remain shared. The environment supplies different ports for time, data, execution and persistence.

## Backtest

Historical data drives deterministic market events and a simulated execution model. Backtests must record assumptions such as fees, slippage, latency and fill model.

## Replay

Replay consumes recorded market and domain events. It is intended for debugging, incident reconstruction, deterministic verification and scenario analysis.

Replay controls should eventually support:

- normal speed
- accelerated speed
- pause/resume
- single-event stepping
- deterministic reruns
- event filtering

## Sandbox / Paper

Sandbox and paper modes use simulated execution while permitting live or replayed market data. They are isolated from real broker credentials and live order submission.

## Live

Live uses a real execution adapter. Live activation must require a valid environment configuration, broker readiness, risk policy and safety checks.

## Scenario and fault injection

The simulator should eventually inject:

- latency
- slippage
- partial fills
- rejects
- delayed acknowledgements
- disconnects
- stale data
- duplicate events
- out-of-order events
- market gaps
- broker outages

Scenario execution must remain deterministic when given the same seed and inputs.

## State and audit

Execution-critical transitions emit domain events. Periodic snapshots may accelerate recovery and reads but are not a substitute for the event history needed for audit/replay.