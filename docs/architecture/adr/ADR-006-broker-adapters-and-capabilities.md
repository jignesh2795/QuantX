# ADR-006: Broker Adapters and Capability Negotiation

Status: Accepted

## Context

Indian brokers expose overlapping but non-identical APIs and capabilities. Conditional logic based on broker names would make the core difficult to extend and test.

## Decision

Every broker is an adapter behind a common broker port and publishes a capability descriptor. The platform selects and validates brokers by capabilities, not by concrete broker identity.

Example capabilities include:

- equities
- futures
- options
- option chain
- multi-leg orders
- historical data
- streaming
- order modification
- margin
- holdings

## Consequences

Strategies can declare requirements and the platform can fail deployment early when a broker cannot satisfy them.

Adapters own authentication, payload conversion, symbol mapping, transport quirks and reconciliation details. Domain code remains vendor-neutral.