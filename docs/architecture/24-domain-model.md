# QuantX Domain Model

Status: Draft

## Core aggregates and value objects

### Instrument
Represents a tradable economic/security identity. Examples: equity, ETF, index, future underlying, option underlying.

### Contract
Represents a venue-tradable contract and carries market-specific constraints such as venue, currency, multiplier, tick size, lot size, expiry, strike and option type where applicable.

### Money
Decimal-safe amount plus explicit currency. No floating-point arithmetic for accounting.

### MarketEvent
Normalized market observation such as trade, quote, bar, order-book update, option-chain update or reference-data event.

### TradeIntent
Strategy-level desired action. It is not a broker order and contains no broker-specific mechanics.

### Order
Canonical requested execution. Contains side, quantity, order type, price constraints, time-in-force and execution metadata.

### Fill
Observed execution result from a venue or simulator.

### Position
Current exposure for a contract, including quantity, average price and realized/unrealized P&L state.

### PositionGroup
Logical grouping for multi-leg strategies, spreads and hedges.

### Portfolio
Capital, exposures, positions, cash, margin, realized/unrealized P&L and allocation state across strategies/accounts.

### RiskDecision
Immutable result of policy/risk evaluation: approve, reject, reduce, transform or require approval.

### ExecutionReport
Normalized venue acknowledgement, rejection, fill or cancellation state.

## Indian-market extensions

The core model must support these from the beginning even if implementation is incremental:

- equities and ETFs
- index instruments
- futures
- options
- expiry
- strike
- call/put
- lot size
- contract multiplier
- margin
- charges/fees
- trading sessions and market calendar
- multi-leg orders and positions

## Multi-leg model

```text
Strategy
  -> Leg definition(s)
  -> Contract selection
  -> Order group
  -> Sequenced execution
  -> Position group
  -> Group-level risk and P&L
```

A multi-leg strategy is not a collection of unrelated single-leg orders.

## Venue-neutrality

Domain objects must not contain broker-specific classes, API payloads, authentication objects or provider-specific symbol formatting. Venue translation belongs in adapters.

## State rules

Trading-critical state changes should be represented by explicit domain events. Mutable infrastructure state must not become the source of truth for accounting.

The initial implementation may use snapshots for efficient reads while retaining immutable event history for audit and replay.