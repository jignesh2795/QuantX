# ADR-004: One Semantic Lifecycle Across Environments

Status: Accepted

## Context

Backtest, sandbox, paper and live systems often drift when each mode implements its own order and position semantics. That makes research less trustworthy and increases operational risk.

## Decision

QuantX uses one canonical trading lifecycle for all execution environments:

```text
Market Event
-> Strategy
-> TradeIntent
-> Policy/Risk
-> Order
-> Execution
-> Fill
-> Position
-> Portfolio
```

Environment-specific behavior is supplied through ports for clock, data, execution and persistence.

## Consequences

Backtests can be compared with paper/live behavior using the same domain contracts. Simulation quality becomes a function of model inputs rather than a separate trading implementation.

Differences that are intentionally environment-specific must be explicit, documented and testable.