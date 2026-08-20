# QuantX Execution Environments

QuantX defines a common trading lifecycle across four primary execution contexts.

## Backtest

Historical data, deterministic clock and simulated execution.

## Sandbox

Live or replayed market data with isolated simulated funds, orders and positions. No live broker order is submitted.

## Paper

The same application semantics as live trading with simulated execution. It is intended for operational rehearsal and strategy validation.

## Live

Real broker execution under full risk, policy, reconciliation and safety controls.

## Invariant

Strategies, intents, risk decisions, orders, fills, positions and portfolio events use the same domain contracts across contexts. Only context-specific ports vary.

```text
Strategy
   ↓
TradeIntent
   ↓
Risk / Policy
   ↓
Order
   ↓
Backtest | Sandbox | Paper | Live
   ↓
Fill
   ↓
Position / Portfolio
```
