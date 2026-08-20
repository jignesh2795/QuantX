# Capital, Allocation, Routing, and Execution Invariants

## Capital

QuantX does not define a universal minimum account capital, starting balance, or strategy capital tier.

Capital sources are explicit:

- `LIVE_BROKER`: fetch the current account financial state from the broker.
- `PAPER_CONFIGURED`: use an explicitly configured paper balance.
- `BACKTEST_CONFIGURED`: use an explicitly supplied experiment starting balance.

A broker, venue, contract, or market may impose an explicit requirement such as minimum order value, minimum quantity, lot size, margin, or product eligibility. Such requirements are represented as constraints and never become universal QuantX defaults.

## Allocation

Capital allocation is evaluated against the current financial state and policy. A strategy cannot assume that a configured amount is available merely because it was requested.

## Routing

Strategies do not select raw broker credentials. Routing resolves an execution request to an eligible account/portfolio/connection using capabilities, permissions, market context, risk state, and routing policy.

## Execution identity

Live-affecting commands carry an `ExecutionContext` identifying account, portfolio, deployment, market, execution mode, and, when resolved, the broker connection.

The same logical strategy may have multiple deployments across accounts or markets without duplicating the strategy definition.

## Isolation

An order for one account must never execute with another account's broker connection. Cross-account aggregation is for reporting/risk views only; physical broker positions remain account-specific.
