# QuantX Architecture Overview

## Product scope

QuantX is an open-source, modular, event-driven trading infrastructure platform with a market-neutral universal core and an India-first implementation.

India is the only fully implemented market module. Digital assets is an interface-only placeholder; other regions remain future work. The architecture does not currently provide multi-currency or FX conversion.

The architecture is designed to remain useful for developers, advanced quant users, and trader-facing applications without making the UI the center of the system.

## Target shape

- modular monolith first
- distributed-ready seams without a distributed runtime requirement
- event-driven domain core
- domain-driven contracts
- ports and adapters
- capability-based integrations
- plugin-first extension model
- data/control/execution plane separation
- market-neutral research, backtest, and paper workflows selected by explicit `MarketContext`
- India-first market policies and F&O-aware domain model
- local-first deployment

LIVE execution is a separate, constrained boundary. It remains India-only and is currently blocked by the project's authoritative risk-evidence requirements.

## Architectural boundary

The core owns portable trading semantics: instruments and market context, orders, fills, positions, portfolio accounting, risk contracts, execution interfaces, clocks, and events.

Market modules own market-specific rules and capabilities. Broker adapters own vendor API behavior, authentication, broker-specific symbols, and transport details. Plugins add optional capabilities without moving vendor dependencies into the universal kernel.

Applications consume stable contracts and compose the required market module and adapters explicitly.

## Initial runtime model

A single local process may host the core, platform services, control plane, and adapters. Interfaces remain explicit so selected workloads can later move into workers or services without rewriting business logic.

This target does not imply that every market, adapter, optional capability, or production execution path is implemented.
