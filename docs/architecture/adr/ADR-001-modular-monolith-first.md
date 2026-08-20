# ADR-001: Modular Monolith First

Status: Accepted

## Context

QuantX needs strong module boundaries, but premature microservices would add deployment, networking, consistency and observability complexity before the product has a stable domain model.

## Decision

Start as a modular monolith with explicit ports, domain contracts, events and module boundaries. Keep the architecture distributed-ready but run it locally as one process by default.

## Consequences

Positive:

- simpler development and local deployment
- easier deterministic testing
- fewer distributed failure modes
- clear path to extract workers later

Negative:

- module boundaries must be enforced by tests/review rather than network isolation
- some future scaling work will require service extraction

## Revisit when

A workload or reliability boundary demonstrates a concrete need for process isolation, independent scaling or independent deployment.