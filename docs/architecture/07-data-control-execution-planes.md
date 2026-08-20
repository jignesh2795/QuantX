# QuantX Data, Control and Execution Planes

QuantX separates three operational planes.

## Data plane

Carries market data, normalized quotes, historical data, order events, fills and internal event streams.

## Control plane

Handles authentication, API requests, strategy registry, scheduling, configuration, Action Center, monitoring and administration.

## Execution plane

Owns order submission, modification, cancellation, broker state, fills and reconciliation.

## Rationale

The separation prevents a slow UI, AI process or research workload from blocking broker execution. It also creates a clean path from a local single-process deployment to worker-based or distributed deployments.

## Initial transport

The local runtime may use an in-process event/message bus. Redis, NATS, ZeroMQ or other transports may be added later behind a stable MessageBus abstraction when scale requires them.
