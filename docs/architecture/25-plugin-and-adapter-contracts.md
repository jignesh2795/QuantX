# Plugin and Adapter Contracts

Status: Draft

## Objective

QuantX must be extensible without forcing contributors to modify the trading core. Plugins add capabilities; adapters connect external systems.

## Adapter categories

```text
BrokerAdapter
MarketDataAdapter
StorageAdapter
MessageBusAdapter
NotificationAdapter
ExternalSignalAdapter
```

## Plugin categories

```text
StrategyPlugin
ResearchPlugin
AnalyticsPlugin
RiskPlugin
ExecutionModelPlugin
AIPlugin
UIExtension
```

## Broker contract

A broker adapter should expose normalized operations for:

- authentication/session
- account/funds
- instruments
- quotes and/or market data capabilities
- order submission
- modification
- cancellation
- order status
- positions
- holdings where supported
- margin where supported
- streaming where supported
- reconciliation
- capabilities
- health/readiness

Broker-specific payloads remain inside the adapter.

## Capability negotiation

Each adapter publishes a capability descriptor. Capability names are stable contract identifiers, not broker-specific conditionals.

Example:

```yaml
capabilities:
  equities: true
  futures: true
  options: true
  option_chain: true
  multi_leg: false
  websocket_orders: true
  historical_data: true
```

Strategies and deployment specifications may declare required capabilities. The platform validates requirements before activation.

## Plugin manifest

Every distributed plugin should declare:

```yaml
name: quantx-example
version: 0.1.0
kind: broker | data | strategy | research | analytics | ai
quantx_api: ">=0.1,<0.2"
capabilities: []
permissions: []
license: MIT
```

## Trust levels

- `trusted`: reviewed infrastructure plugin
- `community`: external plugin with declared permissions
- `sandboxed`: restricted plugin, especially for generated or untrusted code

Sandboxed plugins must not receive broker secrets or unrestricted filesystem/network access.

## Dependency direction

```text
core contracts <- platform implementations <- plugins/adapters
```

A plugin may depend on published QuantX contracts. Core must never import a concrete plugin.

## Contract tests

Every adapter should pass a shared contract suite covering connection, capabilities, read operations, order lifecycle, error handling, recovery and reconciliation where supported.

## Versioning

Plugin and adapter contracts are versioned independently from implementation details. Breaking contract changes require an architecture decision and compatibility period.
