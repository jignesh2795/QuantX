# ADR-002: Plugin-First Extensibility

Status: Accepted

## Context

QuantX needs brokers, data providers, strategies, research tools, analytics, notifications and AI integrations without turning the core into a vendor-specific monolith.

## Decision

Optional functionality should be implemented as plugins or adapters whenever a stable interface can express it. Core contains only the contracts and domain behavior required across environments.

## Rules

- Core never imports a concrete plugin.
- Plugins depend on versioned QuantX contracts.
- Broker and data integrations are adapters.
- Strategy, research, analytics and AI additions are plugins.
- All live execution remains behind the canonical risk/execution path.

## Consequences

The ecosystem is easier to extend and replace, but plugin compatibility and security become first-class concerns. Contract tests, manifests, versioning and trust levels are therefore required.