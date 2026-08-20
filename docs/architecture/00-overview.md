# QuantX Architecture Overview

## Objective

QuantX is an open-source, modular, event-driven trading infrastructure and platform for Indian markets.

The architecture is designed to remain useful for developers, advanced quant users and trader-facing applications without making the UI the center of the system.

## Target shape

- modular monolith first
- distributed-ready seams
- event-driven domain core
- domain-driven contracts
- ports and adapters
- capability-based integrations
- plugin-first extension model
- data/control/execution plane separation
- shared semantics across backtest, sandbox, paper and live
- Indian-market and F&O-first domain model
- local-first deployment

## Architectural boundary

The core owns trading semantics: instruments, contracts, events, money, orders, fills, positions, portfolios, risk, execution and time.

Adapters connect the outside world: brokers, market-data sources, storage, notifications and other services.

Plugins add capabilities: strategies, research, analytics, AI and other optional extensions.

Applications consume stable APIs and SDKs rather than embedding trading logic.

## Initial runtime model

A single local process may host the core, platform services, control plane and adapters. Interfaces are kept explicit so selected workloads can later move into workers or services without rewriting business logic.
