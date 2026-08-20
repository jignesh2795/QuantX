# QuantX Dependency Rules

## Core rule

The domain core must not import UI, broker-specific modules, web frameworks, AI SDKs or storage implementations.

## Dependency direction

```text
Applications
    ↓
Control / Platform Services
    ↓
Domain + Application Ports
    ↑
Adapters / Plugins
```

Adapters depend on contracts defined by QuantX. Core code must not depend on a concrete adapter.

## Allowed examples

- `DhanAdapter -> BrokerPort`
- `VectorResearchPlugin -> ResearchPort`
- `RESTController -> TradingApplicationService`
- `AIPlugin -> StrategyService`

## Forbidden examples

- `RiskEngine -> DhanAdapter`
- `Strategy -> FastAPI`
- `DomainOrder -> SQLAlchemy model`
- `Core -> React`
- `Core -> OpenAI SDK`

## Cross-plugin dependencies

Plugins should prefer shared contracts over direct imports from other plugins. A declared dependency is permitted only when a capability cannot reasonably be expressed through a stable QuantX contract.

## Extraction rule

A module should be considered for extraction into a plugin or adapter when its implementation depends on a venue, provider, optional feature, external framework or optional computation library.
