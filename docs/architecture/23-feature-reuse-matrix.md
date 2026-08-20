# QuantX Feature and Reuse Matrix

Status: architecture planning

This document converts the research phase into explicit reuse decisions. It is a planning artifact, not an implementation specification.

## Decision vocabulary

- **KEEP** — existing idea or component is strong enough to remain central.
- **GENERALIZE** — retain the concept but remove venue/product-specific assumptions.
- **INTEGRATE** — use an established external library/project behind a QuantX port.
- **PLUGIN** — optional capability that should not be required by the core.
- **REPLACE** — concept is useful but the existing implementation should not be carried forward.
- **DEFER** — valuable, but not required for the first stable release.
- **REJECT** — intentionally outside the QuantX product boundary.

## Matrix

| Capability | Primary reference | QuantX decision | Notes |
|---|---|---|---|
| Event-driven domain | QuantumTrade, NautilusTrader | KEEP + GENERALIZE | Core architectural foundation. |
| Deterministic clock | QuantumTrade, NautilusTrader | KEEP | Required for reproducible simulation/replay. |
| Domain contracts | QuantumTrade | KEEP + GENERALIZE | Must cover Indian contracts without becoming India-only internally. |
| Order lifecycle | QuantumTrade, Hummingbot | KEEP + GENERALIZE | Normalize order/fill state transitions. |
| Risk engine | QuantumTrade | KEEP + IMPROVE | Add margin, exposure, concentration, F&O and policy checks. |
| Safety / kill switch | QuantumTrade | KEEP + IMPROVE | Live execution must remain fail-safe. |
| Portfolio accounting | QuantumTrade | KEEP + GENERALIZE | Support multiple accounts, strategies and currencies. |
| Position model | QuantumTrade | GENERALIZE | Extend to futures, options and multi-leg position groups. |
| Broker abstraction | Hummingbot, OpenAlgo | KEEP + GENERALIZE | Core sees capabilities, not broker names. |
| Broker implementations | OpenAlgo ecosystem | PLUGIN | Each broker remains independently replaceable. |
| Market-data adapters | Hummingbot, OpenAlgo | PLUGIN | Separate data from execution where possible. |
| Indian broker support | OpenAlgo | PHASED PLUGIN | Start with a small validated set, then expand through community plugins. |
| F&O contract model | Indian platforms / AlgoTest-style workflows | KEEP + GENERALIZE | Expiry, strike, lots, multiplier and option type are first-class. |
| Multi-leg strategy model | AlgoTest | KEEP + GENERALIZE | Represent legs and order groups explicitly. |
| Greeks | AlgoTest | PLUGIN/CAPABILITY | Not required in the trading kernel. |
| OI/IV/GEX analytics | OpenAlgo ecosystem | PLUGIN/CAPABILITY | Optional analytics modules. |
| Backtest semantics | QuantumTrade, NautilusTrader | KEEP + CONSOLIDATE | One canonical event-driven semantics. |
| Backtest UI execution | Freqtrade | KEEP AS INTERFACE | CLI/API/UI should consume the same engine. |
| Vectorized research | vectorbt | INTEGRATE | Research accelerator, not live execution engine. |
| Optimization | Freqtrade/Jesse/QuantumTrade | PLUGIN/CAPABILITY | Pluggable optimizer interface. |
| Walk-forward analysis | QuantumTrade/Jesse concepts | KEEP | Research layer. |
| Monte Carlo / robustness | QuantumTrade/AlgoTest-style workflows | KEEP + GENERALIZE | Scenario and robustness layer. |
| Paper trading | QuantumTrade/OpenAlgo sandbox concepts | KEEP + GENERALIZE | First-class execution environment. |
| Historical replay | NautilusTrader/QuantumTrade | KEEP | Reuses event model and clock. |
| Fault injection | NautilusTrader-inspired | KEEP AS TEST CAPABILITY | Simulate latency, rejection, gaps and outages. |
| Python strategy SDK | Freqtrade/Jesse/QuantumTrade | KEEP | Primary developer strategy interface. |
| Strategy controllers | Hummingbot Strategy V2 | ADOPT CONCEPT | Long-running strategies can orchestrate reusable executors. |
| Executors | Hummingbot Strategy V2 | ADOPT CONCEPT | Encapsulate finite workflows such as entry, DCA, hedge or exit. |
| Strategy IR | QuantX design | BUILD | Common representation for Python, Flow, AI and external signals. |
| Visual Flow | OpenAlgo/Hummingbot-style UX | PLUGIN/APPLICATION | UI client over the strategy runtime. |
| Webhooks | OpenAlgo-style integrations | CAPABILITY | Convert external signals into validated intents. |
| Strategy scheduler | OpenAlgo-style control plane | CAPABILITY | Scheduling belongs to application/control plane. |
| Strategy registry | OpenAlgo/Freqtrade ecosystem | CAPABILITY | Lifecycle management for strategy definitions. |
| REST API | QuantumTrade v1.6/OpenAlgo | KEEP + HARDEN | Stable public control/data interface. |
| WebSocket API | QuantumTrade v1.6/OpenAlgo/Hummingbot | KEEP + GENERALIZE | Events, market data and execution updates. |
| CLI | QuantumTrade/Freqtrade/Hummingbot | KEEP | Developer and operator interface. |
| Action Center | OpenAlgo | CAPABILITY | Human approval and controlled automation. |
| Monitoring | OpenAlgo/Freqtrade | KEEP + GENERALIZE | Health, latency, orders, events, brokers and strategies. |
| Audit/event trail | QuantumTrade | KEEP | Trading-critical events should be immutable/auditable. |
| Event replay | QuantumTrade/NautilusTrader concepts | KEEP | Debugging, recovery and deterministic investigation. |
| Plugin isolation | QuantX design | BUILD | Trusted/semi-trusted/sandboxed execution levels. |
| Plugin contract testing | Hummingbot-inspired | BUILD | Every adapter/plugin must pass compatibility tests. |
| Storage abstraction | QuantX design | BUILD | DuckDB/Parquet local-first; relational/object storage later. |
| Message bus abstraction | QuantX design | BUILD | In-memory first; Redis/NATS/ZeroMQ/etc. later. |
| AI agents | Hummingbot MCP/OpenAlgo MCP concepts | PLUGIN + DEFER | AI consumes controlled platform APIs; never bypasses risk. |
| Cloud-first deployment | Proprietary platforms | DEFER/REJECT FOR V1 | Local-first and self-hosted first. |
| Crypto market support | QuantumTrade/Hummingbot | PLUGIN/LATER | Keep out of the Indian product core. |
| International markets | NautilusTrader/LEAN | LATER | Universal contracts should permit future expansion. |

## Architectural conclusion

QuantX should not be a clone of any one reference project. The intended combination is:

- QuantumTrade for event-driven trading, risk and safety foundations.
- NautilusTrader for deterministic, research-to-live architecture.
- Hummingbot for connector modularity and controller/executor composition.
- OpenAlgo for Indian broker integration and trading control-plane breadth.
- Indian F&O platforms for derivatives domain workflows.
- Freqtrade/Jesse for strategy developer and research ergonomics.
- vectorbt and other specialist libraries as optional research accelerators.

The core remains small. Capabilities and integrations expand through ports, adapters and plugins.
