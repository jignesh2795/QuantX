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

## Implemented package matrix

The machine-checked matrix is `_ALLOWED_RUNTIME` in `tests/unit/architecture/test_import_boundaries.py`. Current allowed runtime edges (source -> targets):

| Source package | Allowed targets |
|---|---|
| `domain` | none |
| `ports` | `domain` |
| `execution` | `domain`, `ports` |
| `integrations` | `domain`, `execution`, `ports` |
| `persistence` | `domain`, `execution`, `ports`, `research` |
| `research` | `domain`, `ports` |
| `strategy` | `domain`, `execution`, `ports` |
| `india` | `domain`, `ports` |
| `application` | `domain`, `execution`, `integrations`, `persistence`, `ports`, `research`, `strategy` |
| `plugins` | `application`, `domain`, `execution`, `integrations`, `ports` |

Rules that the matrix alone does not express:

- The same matrix applies to `TYPE_CHECKING` imports. The all-edge graph (runtime plus postponed annotations) must contain no package cycle and no cross-package module cycle; there are no deferred-cycle exceptions registered.
- `ports` must never import `execution`. Contracts whose methods accept or return execution records belong to `execution` (`execution/ports.py`, `execution/persistence.py`), not to `ports`.
- `execution` must never import `persistence` infrastructure. Persistence is the implementing side and re-exports the execution-owned protocols for compatibility.
- Removing a contract from `ports` must not leave a compatibility shim that imports it back from `execution`.

## Cross-plugin dependencies

Plugins should prefer shared contracts over direct imports from other plugins. A declared dependency is permitted only when a capability cannot reasonably be expressed through a stable QuantX contract.

## Extraction rule

A module should be considered for extraction into a plugin or adapter when its implementation depends on a venue, provider, optional feature, external framework or optional computation library.
