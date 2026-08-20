# QuantX v0.1 Scope

Status: proposed freeze candidate

## Objective

QuantX v0.1 proves the platform's universal trading core and Indian-market foundation. It should be useful to developers and operators without attempting full feature parity with mature platforms.

## In scope

### Core domain

- Event model and event bus port.
- Deterministic clock abstraction.
- Money and currency primitives.
- Instrument and contract model.
- Order and fill lifecycle.
- Position and portfolio accounting.
- Risk and policy interfaces.
- Execution interfaces.
- Safety and kill-switch interfaces.
- Audit/event trail.

### Execution environments

- Backtest.
- Deterministic replay.
- Paper trading.
- Live execution through adapters.

All environments use the same domain order/fill/position semantics.

### Indian market domain

- Equity and ETF instruments.
- Index instruments.
- Futures contracts.
- Options contracts.
- Expiry, strike, option type, lot size, multiplier and tick size fields.
- Trading-session/calendar abstraction.
- Fee/charge model abstraction.
- Margin/risk model interfaces.
- Multi-leg order-group model.

### Adapters

- Paper broker as a reference adapter.
- One initial Indian broker adapter selected after capability and API validation.
- Market-data adapter interface.
- Historical data ingestion interface.

The initial adapter set is intentionally small; additional brokers remain plugins.

### Developer interfaces

- Python strategy SDK.
- CLI for configuration, validation, backtest, paper and operational commands.
- REST contract for read/control operations.
- WebSocket contract for events, market data and execution updates.
- Plugin manifest and compatibility contract.
- Broker capability negotiation.

### Research

- Canonical event-driven backtest engine.
- Performance metrics.
- Trade/result export.
- Basic parameterized runs.
- Deterministic replay.
- Initial robustness hooks.

External research accelerators are integration points, not required dependencies of the core.

## Explicitly out of scope for v0.1

- Full visual strategy builder.
- AI strategy generation.
- Autonomous AI live trading.
- Multi-account orchestration.
- Large broker matrix.
- Cloud SaaS control plane.
- GEX/volatility-surface analytics.
- Full options-chain research workstation.
- Mobile application.
- Marketplace/plugin registry UI.
- International market coverage.
- Crypto as a core market.
- Microservices deployment as the default architecture.

## v0.1 acceptance gates

### Gate A — domain

Domain contracts can represent equity, futures, options and multi-leg orders without broker-specific fields.

### Gate B — semantics

A strategy can execute under backtest, replay and paper using the same strategy/order/fill lifecycle.

### Gate C — safety

A live order cannot bypass risk, policy checks, capability validation or the safety state machine.

### Gate D — adapters

The reference broker adapter passes the common adapter contract suite.

### Gate E — reproducibility

A deterministic replay reproduces the same event/result sequence from the same event input and configuration.

### Gate F — extensibility

A new strategy and a new adapter can be added without modifying core domain logic.

## v0.1 principle

The release is successful when the architecture proves that QuantX can grow through plugins and adapters without turning the core into a broker- or UI-specific monolith.
