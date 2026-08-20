# Data, Control and Execution Planes

Status: Draft

## Data plane

Carries normalized market observations and replayable events.

Examples:

- quotes
- trades
- bars
- order book updates
- option-chain updates
- reference data
- historical replay events

The data plane should support both synchronous reads and streaming delivery.

## Control plane

Handles low-volume commands and administrative state:

- authentication
- authorization
- strategy lifecycle
- configuration
- scheduling
- deployment
- action center
- monitoring
- audit queries

The control plane should never contain broker-specific trading logic.

## Execution plane

Handles high-integrity state transitions around orders and fills:

```text
TradeIntent
 -> risk/policy
 -> order creation
 -> broker submission
 -> acknowledgement
 -> fills
 -> reconciliation
```

Execution failures must fail closed for live trading.

## Initial implementation

All planes may run in one process. Internal interfaces, events and queues remain explicit so the platform can later deploy them as workers without changing the domain API.

## Scaling rule

Scale a plane only when its workload, fault isolation, or operational requirement justifies it. Do not introduce distributed infrastructure solely for architectural appearance.