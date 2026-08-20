# QuantX Roadmap Alignment

This architecture work incorporates the product-surface lessons from OpenAlgo while preserving the universal event-driven core derived from QuantumTrade/Nautilus-style design.

OpenAlgo-inspired platform capabilities are treated as roadmap layers rather than core-domain dependencies: unified API, broker adapters, WebSockets, sandbox, historical data management, hosted Python strategies, Flow, webhooks, scheduling, Action Center, monitoring, analytics, security and AI/MCP integration.

QuantX additionally keeps these as first-class architecture constraints:

- F&O-native domain semantics
- strategy/runtime symmetry across execution contexts
- plugin and adapter isolation
- capability negotiation
- event replay and deterministic simulation
- local-first, distributed-ready deployment
