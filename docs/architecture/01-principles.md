# QuantX Architectural Principles

## 1. Minimal stable core

Keep the domain kernel small. A feature should remain in core only when trading semantics require it.

## 2. Modular monolith first

Run the platform as one local application initially. Preserve explicit module and interface boundaries so components can later become workers or services.

## 3. Event-driven lifecycle

Represent significant trading state transitions as domain events. Orders, fills, positions, portfolio changes, risk decisions and reconciliation must be observable and replayable.

## 4. Ports and adapters

Core services depend on interfaces. Brokers, market-data providers, storage and external systems implement adapters.

## 5. Plugins by default

Optional strategies, research engines, analytics, AI providers and notifications should be installable capabilities rather than hard-coded core dependencies.

## 6. Capability negotiation

Adapters declare capabilities. Strategies and workflows express requirements. The platform validates compatibility before deployment or execution.

## 7. Shared semantics across environments

Backtest, historical replay, sandbox, paper and live execution use the same domain contracts and lifecycle. Only the data, clock, persistence and execution implementations vary.

## 8. Safety is a boundary

Every live order must pass through the same risk, policy and execution controls regardless of whether the order originated from Python, Flow, an external webhook or an AI agent.

## 9. F&O is first-class

Contracts, expiries, strikes, lots, multipliers, multi-leg positions, margin and option-specific analytics are part of the domain model rather than later add-ons.

## 10. Local-first, distributed-ready

The default experience should work on a single machine. Message buses, worker processes and external storage are replaceable infrastructure choices.

## 11. Integrate mature tooling

Use proven numerical, research, ML and visualization libraries behind stable boundaries instead of rebuilding them inside QuantX.

## 12. API-first applications

Web, CLI, mobile, notebooks and AI agents consume the same service contracts. Applications do not define or duplicate the trading kernel.
