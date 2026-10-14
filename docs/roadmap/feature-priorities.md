# QuantX Feature Priorities

## V0.1 scope — acceptance-complete under ADR-008

The list below records the declared v0.1 scope; it is historical context, not the active implementation queue. The current milestone is M4 Strategy Platform; see `docs/roadmap/README.md`.

- universal event-driven core
- deterministic clock and replay
- instrument/contract model
- equity/futures/options domain foundations
- order/fill/position/portfolio accounting
- risk and kill switch
- paper broker
- one initial Indian broker/data path
- historical data storage
- canonical backtest
- Python strategy interface
- contract tests

## Later platform priority

- REST/WebSocket foundation (M5 control plane; behind Gate 5 per
  `docs/roadmap/decision-gates.md`, not in the declared v0.1 scope)
- CLI (deferred from v0.1 by ADR-008; v0.1 ships the programmatic bootstrap contract instead)
- multi-broker
- sandbox/analyzer
- Historify-style scheduling and data management
- Flow builder
- webhook/external signals
- strategy registry and scheduler
- Action Center
- monitoring and health
- advanced options analytics
- multi-account portfolio
- AI/agents
- plugin registry

## Defer unless justified

- mandatory cloud deployment
- microservice decomposition
- large UI before API/domain stabilization
- full international market support
- broad AI autonomy

A deferred item can move forward when a concrete user need, scale constraint or ecosystem opportunity justifies it.
