# ADR-003: Event-Driven Domain Core

Status: Accepted

## Context

Trading requires auditable state transitions, deterministic simulation, asynchronous market data and reliable order/fill handling. QuantumTrade v1.6 already provides an important reference implementation of this style.

## Decision

QuantX uses an event-driven domain core. Domain state transitions emit explicit events. Subscribers may react asynchronously, but authoritative trading decisions remain deterministic and ordered within the relevant execution context.

## Consequences

Positive:

- replayability
- auditability
- clean WebSocket/event streaming
- easier worker extraction
- common semantics across environments

Negative:

- event contracts require careful versioning
- debugging requires good correlation IDs and event tracing
- event ordering must be defined explicitly

## Required controls

Events must include stable identifiers, timestamps from the QuantX clock, correlation/context metadata and a defined schema version where appropriate.