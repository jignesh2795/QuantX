# Global Trading Architecture Comparison — 2026-11-07

**QuantX baseline:** 99d64996214482a8443ca673f11fbb3b61bdc519 (PR #314 merge).
**Research snapshot:** 2026-11-07.
**Method:** exact upstream revisions, inspected implementation and test paths, QuantX equivalents, explicit adoption decisions.

This is a technical source review, not an upstream benchmark, a complete security audit, a licensing opinion, or an end-to-end test of the referenced systems. Upstream tests were inspected, not executed in this research task. No code was copied, no dependencies were installed, and no broker/API/sandbox operations occurred.

## 1. Executive conclusion

**Recommended next vertical: M4.5 — a minimal declarative Flow compiler that uses the existing QuantX StrategyRuntime.**

QuantX has completed the historical data/research provenance sequence R1-C1 through R1-C14, and its Python strategy path now includes StrategyDefinition, deterministic StrategyIR, registry, runtime, deployment validation, risk/policy preparation and offline paper/backtest rehearsal. The parent M4 exit criterion is still open: a first Flow authoring path must share the runtime semantics already proven by Python strategies.

The comparison supports these decisions:

- **LEAN:** adapt the separation of brokerage policy from transaction orchestration, plus concurrency and transaction-handler test patterns.
- **NautilusTrader:** adapt execution/client/reconciliation separation and property-based reconciliation tests.
- **Hummingbot:** adapt connector-owned lifecycle, order tracking and throttling tests. Reject converting invalid financial values to zero and do not assume its backtest simulator is identical to the live path.
- **OpenAlgo:** use as an India-focused product/control-plane and broker-service reference. Reject its direct-order Flow nodes as a QuantX strategy model.
- **CCXT and Indian broker SDKs:** use as transport/API contract references only, not as strategy engines or risk authorities.

The first Flow slice should be declarative and deterministic. A Flow definition is validated and compiled to an implementation of the existing ExecutableStrategy protocol, then invoked through StrategyRuntime. Deployment-owned context, StrategyExecutionPreparer, risk/policy and the existing paper/backtest consumers remain canonical.

This recommendation does **not** implement Flow, add a market, add a connector, change LIVE eligibility or authorize broker operations. India remains the only implemented market.

## 2. Immutable upstream revisions

All commits below were read from GitHub on 2026-11-07 and pinned for this comparison.

| Project | Default branch | Exact commit | Commit date (UTC) | Role |
|---|---|---|---|---|
| [LEAN](https://github.com/QuantConnect/Lean/tree/cc98c42f5543256cea0a33e4521401e42303b7d7) | master | cc98c42f5543256cea0a33e4521401e42303b7d7 | 2026-11-06 | Full trading engine; brokerage models and transaction handling |
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader/tree/9639304245707e6ee5c73c96c62f43ba2b464959) | develop | 9639304245707e6ee5c73c96c62f43ba2b464959 | 2026-11-07 | Event-driven engine; execution and reconciliation |
| [Hummingbot](https://github.com/hummingbot/hummingbot/tree/9af100d6822da7d2d0291a906c730ef172284ee2) | master | 9af100d6822da7d2d0291a906c730ef172284ee2 | 2026-09-22 | Connector framework and strategy/executor decomposition |
| [OpenAlgo](https://github.com/marketcalls/openalgo/tree/a1b9e32506bce21403a8614dddeed0ab61fd519a) | main | a1b9e32506bce21403a8614dddeed0ab61fd519a | 2026-11-06 | India-focused broker/API control plane |
| [CCXT](https://github.com/ccxt/ccxt/tree/a31f168905acea92c05d20750eda0d7ac350eb70) | master | a31f168905acea92c05d20750eda0d7ac350eb70 | 2026-11-05 | Unified exchange client and market metadata |
| [Kite Connect Python](https://github.com/zerodha/pykiteconnect/tree/2f67c46ead6864425744abe5ec386979ee39c69f) | master | 2f67c46ead6864425744abe5ec386979ee39c69f | 2026-09-15 | Official Zerodha API wrapper |
| [DhanHQ Python](https://github.com/dhan-oss/DhanHQ-py/tree/8c6583e6e169fd0293e2271cb5fcb5aad3f8e805) | main | 8c6583e6e169fd0293e2271cb5fcb5aad3f8e805 | 2026-10-08 | Official Dhan API wrapper and statement methods |
| [Upstox Python](https://github.com/upstox/upstox-python/tree/d88a12ef5738a4c8d71f3b88eb7b79a359277c9d) | master | d88a12ef5738a4c8d71f3b88eb7b79a359277c9d | 2026-09-07 | Official Upstox REST and streaming client |

## 3. Comparative decision matrix

| System | Primary role | Strongest relevant pattern | Limitation for QuantX | Decision |
|---|---|---|---|---|
| LEAN | Full research/backtest/live engine | Brokerage policy is separate from transaction handling | Large .NET engine and broad domain would duplicate QuantX | Adapt selected seams/tests |
| NautilusTrader | Event-driven trading engine | Explicit execution/client/reconciliation modules and property tests | Rust/Python scale and runtime structures are not drop-in durability guarantees | Adapt seams/tests |
| Hummingbot | Exchange connector and strategy/executor platform | Active/cached/lost order tracking; connector throttling and stream lifecycle | Crypto-centric contracts and distinct DataFrame simulator path | Adapt selectively; reject unsafe numeric fallback |
| OpenAlgo | India-first broker/API control plane | Route/service/adapter layering and unanswered-write handling | Direct-order Flow graph differs from QuantX strategy-intent boundary | Adapt product/transport ideas; reject direct-order Flow |
| CCXT | Unified exchange API client | Common exchange methods and market metadata | No strategy lifecycle, durable execution, risk authority or research provenance | Defer until justified crypto scope |
| Kite, Dhan, Upstox SDKs | Broker API wrappers | Concrete endpoint parameters, status vocabularies and stream payloads | SDK methods do not prove completeness or authority | Reference only |

## 4. Source findings and QuantX implications

### 4.1 LEAN — brokerage policy and transaction handling

**Inspected source and tests**

- Engine/TransactionHandlers/BrokerageTransactionHandler.cs — [pinned source](https://github.com/QuantConnect/Lean/blob/cc98c42f5543256cea0a33e4521401e42303b7d7/Engine/TransactionHandlers/BrokerageTransactionHandler.cs).
- Common/Brokerages/IBrokerageModel.cs — [pinned interface](https://github.com/QuantConnect/Lean/blob/cc98c42f5543256cea0a33e4521401e42303b7d7/Common/Brokerages/IBrokerageModel.cs).
- Brokerages/Brokerage.cs — [pinned base](https://github.com/QuantConnect/Lean/blob/cc98c42f5543256cea0a33e4521401e42303b7d7/Brokerages/Brokerage.cs).
- Common/Orders/Order.cs — [pinned order model](https://github.com/QuantConnect/Lean/blob/cc98c42f5543256cea0a33e4521401e42303b7d7/Common/Orders/Order.cs).
- Tests/Engine/BrokerageTransactionHandlerTests/ — [transaction-handler tests](https://github.com/QuantConnect/Lean/tree/cc98c42f5543256cea0a33e4521401e42303b7d7/Tests/Engine/BrokerageTransactionHandlerTests).
- Tests/Brokerages/BrokerageConcurrentMessageHandlerTests.cs — [concurrency test](https://github.com/QuantConnect/Lean/blob/cc98c42f5543256cea0a33e4521401e42303b7d7/Tests/Brokerages/BrokerageConcurrentMessageHandlerTests.cs).

**Finding**

LEAN places account/broker-specific policy in IBrokerageModel: account type, buying-power requirements, submission/update/execution permissions, leverage, fill/fee/slippage and other brokerage behavior. BrokerageTransactionHandler owns request processing and transaction lifecycle. Brokerage.cs exposes connection lifecycle and events for order/status/account notifications. Order properties have an extension point for additional venue-specific metadata.

**QuantX mapping and decision**

QuantX already separates BrokerAdapter/capabilities, market packs, market rules and application execution. Do not create another parallel policy hierarchy. Reuse the design principle only when a demonstrated policy ownership gap exists: broker protocol constraints belong in the broker adapter/capability seam; market rule economics belong in versioned market-pack policy; transaction ordering and durable lifecycle remain in the canonical execution layer.

**ADAPT:** selected policy separation and concurrency/message-ordering tests. **REJECT:** wholesale C# engine/domain duplication or copying venue-specific behavior as a universal default.

### 4.2 NautilusTrader — event-driven execution and reconciliation

**Inspected source and tests**

- ADAPTERS.md — [pinned adapter guidance](https://github.com/nautechsystems/nautilus_trader/blob/9639304245707e6ee5c73c96c62f43ba2b464959/ADAPTERS.md).
- crates/execution/src/engine/ — [execution engine](https://github.com/nautechsystems/nautilus_trader/tree/9639304245707e6ee5c73c96c62f43ba2b464959/crates/execution/src/engine).
- crates/execution/src/client/ — [execution clients](https://github.com/nautechsystems/nautilus_trader/tree/9639304245707e6ee5c73c96c62f43ba2b464959/crates/execution/src/client).
- crates/execution/src/reconciliation/ — [reconciliation modules](https://github.com/nautechsystems/nautilus_trader/tree/9639304245707e6ee5c73c96c62f43ba2b464959/crates/execution/src/reconciliation).
- crates/execution/src/reconciliation/proptests.rs — [property-based tests](https://github.com/nautechsystems/nautilus_trader/blob/9639304245707e6ee5c73c96c62f43ba2b464959/crates/execution/src/reconciliation/proptests.rs).
- crates/execution/src/reconciliation/tests.rs — [reconciliation tests](https://github.com/nautechsystems/nautilus_trader/blob/9639304245707e6ee5c73c96c62f43ba2b464959/crates/execution/src/reconciliation/tests.rs).

**Finding**

Execution, venue clients and reconciliation have explicit module boundaries. Property tests deliberately generate shuffled, duplicated and dropped fill/report sequences and assert venue position quantity, average price, P&L and deterministic synthetic identifiers. This is stronger than a small set of static happy-path examples for reconciliation logic.

**QuantX mapping and decision**

QuantX has a canonical lifecycle reducer, durable persistence, pending/recovery gates and explicit receipt/UNKNOWN handling. Adopt property-based tests for duplicate, reordered, missing, delayed and contradictory evidence, but preserve QuantX's durable journal and fail-closed semantics. Do not introduce a second lifecycle table, accounting engine, event store or recovery authority.

**ADAPT:** reconciliation seams and property-based test strategy. **DEFER:** Rust rewrite/full platform scale.

### 4.3 Hummingbot — connector tracking and executor lifecycle

**Inspected source and tests**

- hummingbot/connector/client_order_tracker.py — [order tracker](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/connector/client_order_tracker.py).
- hummingbot/connector/exchange_py_base.py — [exchange connector base](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/connector/exchange_py_base.py).
- hummingbot/strategy_v2/controllers/controller_base.py — [controller base](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/controllers/controller_base.py).
- hummingbot/strategy_v2/executors/executor_base.py — [executor base](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/executors/executor_base.py).
- hummingbot/strategy_v2/backtesting/backtesting_engine_base.py and executor_simulator_base.py — [backtesting engine](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/backtesting/backtesting_engine_base.py), [executor simulator](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/hummingbot/strategy_v2/backtesting/executor_simulator_base.py).
- test/hummingbot/connector/test_client_order_tracker.py — [tracker tests](https://github.com/hummingbot/hummingbot/blob/9af100d6822da7d2d0291a906c730ef172284ee2/test/hummingbot/connector/test_client_order_tracker.py).

**Finding**

The order tracker distinguishes in-flight, cached and lost orders; connector bases own throttling, time synchronization and stream trackers. Strategy V2 separates controllers from reusable executor lifecycles. The inspected backtest implementation uses separate executor simulators and tabular historical snapshots; that source does not prove exact live/backtest path parity.

One unsafe helper converts non-finite numeric values to Decimal zero. QuantX must not copy this: invalid or missing money, P&L, quantity or exposure must remain invalid/incomplete, never become a plausible zero.

**QuantX mapping and decision**

QuantX already has canonical order lifecycle, broker adapters and separate paper/backtest drivers. The best reuse is test design around connector lifecycle, order identity, cache expiry, duplicate/out-of-order updates, throttling, and recovery—not copying Hummingbot's crypto-centric model.

**ADAPT:** connector lifecycle and tracker test patterns. **REJECT:** non-finite-to-zero numeric handling and assuming a separate simulator is parity proof. **DEFER:** crypto-specific contract types.

### 4.4 OpenAlgo — India control plane, services and Flow

**Inspected source and design records**

- docs/design/README.md — [design index](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/docs/design/README.md).
- docs/design/27-service-layer/README.md — [service layer](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/docs/design/27-service-layer/README.md).
- docs/design/19-placeorder-flow/README.md — [place-order flow](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/docs/design/19-placeorder-flow/README.md).
- docs/design/10-flow-architecture/README.md — [Flow architecture](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/docs/design/10-flow-architecture/README.md).
- services/place_order_service.py — [order service](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/services/place_order_service.py).
- utils/httpx_client.py — [transport uncertainty](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/utils/httpx_client.py).
- utils/broker_backpressure.py — [bounded backpressure](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/utils/broker_backpressure.py).
- Tests: [test_unanswered_order_writes.py](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/test/test_unanswered_order_writes.py), [test_broker_protocol.py](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/test/test_broker_protocol.py), [test_flow_lifecycle_guards.py](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/test/test_flow_lifecycle_guards.py), [test_flow_workflow_validator.py](https://github.com/marketcalls/openalgo/blob/a1b9e32506bce21403a8614dddeed0ab61fd519a/test/test_flow_workflow_validator.py).

**Finding**

OpenAlgo is an India-focused self-hosted broker/API and control-plane product. Its documented route/service/broker separation, optional sandbox and real-time data features are useful product references. Its transport distinguishes safe read retries from writes that may have reached the broker, and its backpressure policy can reject a request before reserving a queue slot. Its Flow node model includes direct PlaceOrder/Modify/Cancel operations.

**QuantX mapping and decision**

QuantX has a different intended architecture: strategy authoring expresses intent; StrategyRuntime validates output; deployment-owned context, StrategyExecutionPreparer, risk/policy and canonical execution own downstream effects. A Flow node must not call the broker or dispatch an order directly.

**ADAPT:** service layering, unanswered-write semantics, pre-send rate refusal, graph validation and lifecycle test ideas. **REJECT:** direct-order Flow graph and mode/auth behavior as strategy-runtime semantics. **DEFER:** visual editor, webhooks, scheduling, hosted workers and MCP.

### 4.5 CCXT — exchange API client only

**Inspected source:** [ts/src/base/Exchange.ts](https://github.com/ccxt/ccxt/blob/a31f168905acea92c05d20750eda0d7ac350eb70/ts/src/base/Exchange.ts), exposing a large unified exchange method surface.

CCXT can reduce exchange API-client duplication. It does not supply strategy lifecycle, durable order/receipt journal, QuantX risk authority, point-in-time research provenance or market-pack rules.

**Decision — DEFER.** Digital assets remains a placeholder. Revisit CCXT only against a specific venue/product requirement, source/data constraints and separate market eligibility review. Treat outputs as adapter data, not QuantX execution authority.

### 4.6 Indian broker SDKs — API contracts only

**Inspected source**

- Kite Connect: [kiteconnect/connect.py](https://github.com/zerodha/pykiteconnect/blob/2f67c46ead6864425744abe5ec386979ee39c69f/kiteconnect/connect.py) — route constants and broker-specific exchange/product/order/TIF/status vocabularies.
- DhanHQ: [src/dhanhq/_order.py](https://github.com/dhan-oss/DhanHQ-py/blob/8c6583e6e169fd0293e2271cb5fcb5aad3f8e805/src/dhanhq/_order.py), [portfolio](https://github.com/dhan-oss/DhanHQ-py/blob/8c6583e6e169fd0293e2271cb5fcb5aad3f8e805/src/dhanhq/_portfolio.py), [statement methods](https://github.com/dhan-oss/DhanHQ-py/blob/8c6583e6e169fd0293e2271cb5fcb5aad3f8e805/src/dhanhq/_statement.py), and [statement wrapper tests](https://github.com/dhan-oss/DhanHQ-py/blob/8c6583e6e169fd0293e2271cb5fcb5aad3f8e805/tests/unit/test_dhanhq_statement.py).
- Upstox: [generated order API](https://github.com/upstox/upstox-python/blob/d88a12ef5738a4c8d71f3b88eb7b79a359277c9d/upstox_client/api/order_api.py), [market-data streamer](https://github.com/upstox/upstox-python/blob/d88a12ef5738a4c8d71f3b88eb7b79a359277c9d/upstox_client/feeder/market_data_streamer_v3.py), [portfolio streamer](https://github.com/upstox/upstox-python/blob/d88a12ef5738a4c8d71f3b88eb7b79a359277c9d/upstox_client/feeder/portfolio_data_streamer.py).

**Finding**

Official SDKs are useful for endpoint parameters, status vocabularies, auth, pagination and stream messages. SDK method presence does not establish source completeness, freshness, economic meaning, account identity or authoritative P&L. Dhan's inspected order wrapper uses float for price/trigger-price payloads; that is not a QuantX financial-domain precedent.

**Decision — REFERENCE ONLY.** Use official specifications for adapter fixtures and deterministic conformance tests; no new adapter or LIVE evidence source is justified by this comparison. Keep exact Decimal validation in QuantX domain and isolate lossy vendor serialization at the transport boundary.

## 5. Cross-project patterns worth reusing

1. Separate broker/market policy from transaction orchestration.
2. Keep execution, connector protocol and reconciliation boundaries explicit.
3. Test shuffled, duplicated, delayed, missing and contradictory evidence rather than only happy paths.
4. Give adapters ownership of stream lifecycle, throttling, broker IDs and transport uncertainty.
5. Keep authoring separate from authorization: strategies and Flow produce validated intent; deployment/risk/policy/execution remain authoritative.
6. Preserve exact financial values and explicit incomplete/UNKNOWN evidence.

## 6. Anti-patterns to reject

- Direct broker, HTTP, REST order endpoint or LIVE capability in strategy or Flow nodes.
- A second lifecycle reducer, accounting ledger, event store or research identity system.
- Automatic retry of a write whose outcome is UNKNOWN.
- Converting missing/non-finite P&L, exposure, quantity or price into zero.
- Assuming a simulator equals the live path without parity tests.
- Assuming SDK method availability proves account-state completeness or LIVE evidence authority.
- Adding a new market/connector merely because an upstream project supports it.

## 7. QuantX gap map at the reviewed baseline

| Responsibility | Existing QuantX seam | Gap / disposition |
|---|---|---|
| Market context | src/quantx/markets/registry.py and markets/india | Explicit context and caller-populated registry exist; India only |
| Broker abstraction | src/quantx/ports/broker.py and src/quantx/plugins/dhan | Keep SDKs in adapters; do not widen #267 without new source |
| Order lifecycle | src/quantx/execution/order_lifecycle.py and persistence | Keep canonical reducer and durable journal |
| Strategy IR | src/quantx/strategy/compiler.py, ir.py and registry.py | Python authoring path exists; no Flow compiler package |
| Strategy invocation | src/quantx/strategy/runtime.py and context.py | Reuse existing ExecutableStrategy and StrategyRuntime |
| Deployment/risk | src/quantx/strategy/deployment.py and execution.py | Keep deployment-owned context and canonical risk/policy preparation |
| Research/data | src/quantx/research and R1-C1–C14 | Provenance/ingestion spine complete; don't restart C14 |
| LIVE evidence | src/quantx/plugins/dhan/risk_evidence.py and #267 | Still blocked; no new authoritative provider discovered |

## 8. Recommended next bounded milestone — M4.5 Flow-to-existing-runtime parity

**Objective:** one small declarative Flow produces the same validated strategy-result semantics as an equivalent Python strategy under identical StrategyContext, using the existing StrategyRuntime and offline paper/backtest consumers.

### Architecture

- Define a typed, versioned FlowDefinition with immutable nodes and edges.
- Validate node types, ports, edge types, required inputs, unique IDs, cycles, parameters and market context before evaluation.
- Compile to a typed deterministic plan. Do not serialize arbitrary Python or store executable expressions as unvalidated strings.
- Implement a Flow adapter conforming to the existing ExecutableStrategy protocol and invoke it through StrategyRuntime.
- Preserve StrategyIR as canonical identity/version/market/parameter metadata unless a demonstrated requirement justifies a versioned extension. Do not overload its string parameter tuple with raw graph JSON.
- Continue through deployment-owned binding, StrategyExecutionPreparer, risk/policy and existing paper/backtest consumers.

### Minimal v1 node set

Context and market-data inputs already present in StrategyContext; bounded same-instrument history; pure arithmetic/comparison/boolean operations; only indicators with an existing deterministic function and test contract; explicit StrategySignal output and optional TradeIntent construction through the existing domain contract.

### Exclusions

No direct broker/order/REST calls, account writes, arbitrary Python, network/filesystem access, hidden mutable state, sleep/wall-clock timer, scheduling, webhook, streaming, optimization, AI-generated nodes, cross-instrument graph fan-out, visual UI, distributed worker, new persistence architecture or LIVE capability.

### Acceptance matrix

1. Compiler purity and deterministic canonical identity for the same definition/compiler version.
2. Invalid node/edge/port/parameter/context, duplicate IDs, cycles and disconnected required inputs fail before evaluation with stable diagnostics.
3. Same Flow program plus identical StrategyContext and run-scoped state produces the same StrategyResult.
4. Equivalent Python and Flow strategies produce equivalent signal/intent fields and event times under identical context.
5. History is same-instrument, bounded, strictly prior and point-in-time; no future evidence.
6. Missing/incomplete data remains unavailable/UNKNOWN; no manufactured zero, mark or position.
7. HOLD cannot carry executable intent; BUY/SELL side and identity remain enforced by existing runtime checks.
8. Static/AST and runtime tests prove no broker, HTTP, order-submit, account-write, LIVE or arbitrary-code capability.
9. Results pass through existing deployment binding, risk/policy and paper/backtest paths; no parallel executor.
10. Definition version, canonical representation and existing provenance make runs reproducible.

### Bounded sequence

- **F4.5.1:** domain contract, immutable nodes/edges, version, canonical identity and graph validator.
- **F4.5.2:** pure compiler/interpreter for minimal deterministic node set.
- **F4.5.3:** adapter to ExecutableStrategy and Python/Flow parity tests.
- **F4.5.4:** offline paper/backtest rehearsal reusing existing deployment and execution preparation.

**Decision:** recommended next Strategy Platform implementation slice. This is a new parent-M4 vertical, not a reopening of QX-08. It does not resolve or weaken #266/#267 or implement global/crypto markets.

## 9. Operating and evidence limitations

This comparison does not include performance benchmarks, full dependency/security audits, licensing compatibility analysis, commercial-use analysis, regulatory advice or end-to-end testing of upstream projects. Upstream branches can move after this snapshot; use the pinned revisions for this report's conclusions.

Official documentation reviewed for context: [LEAN brokerage models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/brokerages/key-concepts), [NautilusTrader execution](https://nautilustrader.io/docs/latest/concepts/execution/) and [backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/), [Hummingbot Strategy V2](https://hummingbot.org/strategies/v2-strategies/) and [connectors](https://hummingbot.org/connectors/), [OpenAlgo design index](https://github.com/marketcalls/openalgo/tree/a1b9e32506bce21403a8614dddeed0ab61fd519a/docs/design), [CCXT source](https://github.com/ccxt/ccxt/tree/a31f168905acea92c05d20750eda0d7ac350eb70), [Kite Connect](https://kite.trade/docs/connect/v3/), [Dhan V2](https://dhanhq.co/docs/v2/) and [Upstox API](https://upstox.com/developer/api-documentation/). External API rules/limits may change and must be rechecked at implementation time.

No broker credentials, real API calls, sandbox, production or LIVE operations were used. The research recommendation changes no current execution or risk authority.
