# QuantX Unified Architecture Specification

Status: Draft for architecture review  
Branch: `docs/architecture-roadmap`

## 1. Purpose

QuantX is an open-source, Indian-market-first trading infrastructure and platform built around a universal event-driven trading core. The architecture is intentionally modular, plugin-based, capability-driven, local-first, and suitable for later distributed deployment.

The platform is not a broker wrapper, a strategy builder, or an AI agent. Those are capabilities around the core trading lifecycle.

## 2. Architectural shape

```text
Clients: Web UI / CLI / SDK / AI / External Signals
                         |
                  REST / WebSocket
                         |
                  CONTROL PLANE
        auth / registry / scheduler / monitoring
                         |
                  APPLICATION SERVICES
       trading / research / portfolio / automation
                         |
                   DOMAIN CORE
 events / clock / money / instruments / orders / fills
 positions / portfolios / risk / execution / policies
                         |
                    PORTS
        broker / data / storage / message bus / notify
                         |
                    ADAPTERS
      brokers / market data / databases / transports
                         |
                  external systems
```

## 3. Six architectural layers

### Domain core
Stable trading semantics: contracts, events, time, money, orders, fills, positions, portfolios, policies, risk, execution and safety.

### Trading platform
Strategies, simulation, backtesting, paper trading, optimization, analytics, scheduling and research.

### Control plane
API, WebSocket control, authentication, authorization, strategy registry, scheduler, action center, health, audit and operations.

### Adapter platform
Broker adapters, data adapters, storage implementations, message-bus transports and external integrations.

### Client applications
Web, CLI, notebooks, mobile and other clients. Clients consume the platform API; they do not define domain behavior.

### Intelligence layer
Research assistants, strategy generation, optimization assistants, anomaly detection and agent workflows. Intelligence uses the same controlled platform interfaces as other clients.

## 4. Trading lifecycle

```text
Market/Data Event
      -> Strategy / Controller
      -> TradeIntent
      -> Policy + Risk Decision
      -> Order
      -> Execution
      -> Fill
      -> Position Update
      -> Portfolio Update
      -> Event Store / Event Bus
```

Backtest, historical replay, sandbox, paper and live modes share these semantics. They differ primarily in clock, data source, execution venue and persistence configuration.

## 5. Deployment model

QuantX starts as a modular monolith. Internal boundaries are explicit so components can later move into workers or services without changing domain contracts.

Small deployment:

```text
QuantX process + local storage + in-memory bus
```

Advanced deployment:

```text
API / Control
Data workers
Research workers
Execution workers
Event bus
Shared persistence
```

Distributed operation is an optimization, not a prerequisite for correctness.

## 6. Planes

### Data plane
Market data, events, quotes, historical data and replay streams.

### Control plane
Authentication, configuration, strategy lifecycle, scheduling, monitoring and user commands.

### Execution plane
Order submission, acknowledgement, fills, reconciliation, broker state and live safety.

These planes may share a process initially but are separated by contracts.

## 7. Plugin rule

The default architectural question for a non-core feature is:

> Can this be an adapter, plugin, or external integration instead of core code?

Core must not depend on a specific broker, data vendor, UI, AI vendor or notification service.

## 8. Safety boundary

No strategy, webhook, AI agent or third-party plugin may directly bypass the canonical risk and execution lifecycle for live trading.

All live orders pass through:

```text
TradeIntent -> Policy -> Risk -> Order -> Execution -> Reconciliation
```

## 9. Architecture maturity rule

A component may move from plugin to core only when it becomes a stable cross-domain contract required by the platform. Conversely, optional capabilities should remain replaceable.

## 10. Current status

This document is an architecture target, not an implementation specification for every class. Detailed domain contracts and interfaces will be specified before production implementation begins.