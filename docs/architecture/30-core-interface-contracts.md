# QuantX v0.1 Core Interface Contracts

## Purpose

These interfaces define the boundaries that implementation must preserve. Concrete implementations may evolve without changing the core domain semantics.

## 1. Market data

```python
class MarketDataPort(Protocol):
    def capabilities(self) -> MarketDataCapabilities: ...
    def subscribe(self, request: MarketDataSubscription) -> SubscriptionHandle: ...
    def unsubscribe(self, handle: SubscriptionHandle) -> None: ...
    def snapshot(self, request: MarketDataRequest) -> MarketSnapshot: ...
    def history(self, request: HistoricalDataRequest) -> HistoricalData: ...
```

Market data providers must normalize vendor-specific symbols and timestamps into QuantX contracts.

## 2. Broker / execution

```python
class BrokerPort(Protocol):
    def capabilities(self) -> BrokerCapabilities: ...
    def account(self) -> AccountSnapshot: ...
    def submit(self, command: OrderCommand) -> OrderAck: ...
    def modify(self, command: ModifyOrderCommand) -> OrderAck: ...
    def cancel(self, command: CancelOrderCommand) -> OrderAck: ...
    def orders(self) -> list[OrderState]: ...
    def positions(self) -> list[BrokerPosition]: ...
    def fills(self, request: FillQuery) -> list[Fill]: ...
    def reconcile(self) -> ReconciliationSnapshot: ...
```

The broker port must not expose raw broker SDK types to domain code.

## 3. Execution

```python
class ExecutionPort(Protocol):
    def execute(self, command: OrderCommand) -> ExecutionResult: ...
    def cancel(self, order_id: OrderId) -> CancellationResult: ...
```

Execution always sits downstream of policy and risk validation.

## 4. Risk

```python
class RiskPort(Protocol):
    def evaluate(self, intent: TradeIntent, context: RiskContext) -> RiskDecision: ...
```

A strategy cannot bypass this port.

## 5. Strategy

```python
class Strategy(Protocol):
    metadata: StrategyMetadata

    def on_start(self, context: StrategyContext) -> None: ...
    def on_market(self, event: MarketEvent) -> list[TradeIntent]: ...
    def on_fill(self, fill: Fill) -> list[TradeIntent]: ...
    def on_stop(self, context: StrategyContext) -> None: ...
```

Strategies create intents, not broker orders.

## 6. Strategy IR

The declarative representation must be independent of a particular UI or model provider.

```text
StrategyDefinition
 ├── metadata
 ├── universe
 ├── indicators
 ├── conditions
 ├── entry rules
 ├── exit rules
 ├── position rules
 ├── risk policy reference
 └── execution policy reference
```

Python strategies may execute directly against the runtime while visual and AI strategies compile into a compatible representation.

## 7. Portfolio

```python
class PortfolioPort(Protocol):
    def snapshot(self) -> PortfolioSnapshot: ...
    def apply(self, event: PortfolioEvent) -> None: ...
    def exposure(self) -> ExposureSnapshot: ...
```

## 8. Persistence

```python
class EventStorePort(Protocol):
    def append(self, events: Sequence[DomainEvent]) -> None: ...
    def load(self, stream: StreamId, after: EventId | None = None) -> list[DomainEvent]: ...
    def snapshot(self, state: StateSnapshot) -> None: ...
```

State stores and event stores are separate abstractions even if v0.1 uses the same local backend.

## 9. Message bus

```python
class MessageBusPort(Protocol):
    def publish(self, event: DomainEvent) -> None: ...
    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> Subscription: ...
```

The default local implementation may be in-process. Redis/NATS/ZeroMQ/Kafka-style transports can be later implementations.

## 10. Secrets

```python
class SecretsPort(Protocol):
    def get(self, reference: SecretReference) -> SecretValue: ...
    def put(self, reference: SecretReference, value: SecretValue) -> None: ...
```

Strategy plugins and AI agents must not receive unrestricted secret access.

## 11. Reconciliation

```python
class ReconciliationPort(Protocol):
    def reconcile(self) -> ReconciliationReport: ...
```

Reconciliation is required before a live runtime can safely resume after restart or connection loss.

## 12. Plugin contract

Every plugin declares:

```text
name
version
plugin_type
quantx_api_range
capabilities
permissions
required_plugins
license
maintainer
```

The runtime validates compatibility before loading the plugin.

## 13. Capability model

Capabilities are data, not broker-specific conditionals.

Examples:

```text
supports_equities
supports_futures
supports_options
supports_option_chain
supports_websocket
supports_historical_data
supports_basket_orders
supports_modify_order
supports_margin_query
supports_shorting
```

Strategies and workflows may declare required capabilities.

## 14. Execution environments

All environments consume the same domain contracts:

```text
Backtest
Replay
Sandbox
Paper
Live
```

The environment supplies different clock, data, execution and persistence implementations; it does not create a second trading model.

## 15. Idempotency

All externally retried commands that can create side effects require an idempotency key or deterministic client command identity.

At-least-once messaging is acceptable; duplicate side effects are not.

## 16. Recovery

Live startup sequence:

```text
load configuration
→ initialize adapters
→ connect
→ fetch remote orders/fills/positions
→ reconcile
→ rebuild local state
→ evaluate safety state
→ only then enable live commands
```

## 17. Contract tests

Every broker adapter must pass the common broker contract test suite. Every plugin must pass plugin manifest/version/capability validation.
