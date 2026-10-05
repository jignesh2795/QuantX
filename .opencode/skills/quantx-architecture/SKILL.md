---
name: quantx-architecture
description: Use when adding, moving, or refactoring code in QuantX and deciding WHERE it belongs — package placement, module boundaries, dependency rules, ports and adapters, event-driven domain core, layering (domain/application/execution/integrations/plugins/ports/persistence/india). Front-load keywords: architecture, package placement, where to put code, new module, port, adapter, boundary, dependency rule.
---

# QuantX Architecture & Code Placement

QuantX is a **modular monolith first, distributed-ready later**: event-driven, domain-driven, ports-and-adapters, plugin-first. Canonical docs: `docs/architecture/README.md` (reading order starts `00-overview` → `01-principles` → `02-dependency-rules`).

## Package map (`src/quantx/`)

| Package | Responsibility |
|---|---|
| `domain/` | Broker-neutral business objects, value objects, events, rules, EventBus. **Zero broker SDK types.** |
| `application/` | Use cases/orchestration. Does not own market-specific rules. |
| `execution/` | Normalized execution semantics + safety boundaries (paper, receipts, preconditions, idempotency, transactions). |
| `integrations/` | Broker/account/venue adapters + reconciliation evidence. (No `__init__.py` — namespace package.) |
| `plugins/` | Concrete replaceable vendors (`dhan/`, `reference_broker/`). |
| `ports/` | The two stable contracts the core depends on: `broker.py`, `market_data.py`. |
| `persistence/` | DB-neutral contracts + `sqlite/` implementation behind `UnitOfWork`. |
| `research/` | Historical data, provenance, replay, experiments. |
| `strategy/` | Strategy IR + compiler/registry/runtime. |
| `india/` | India-market specifics — deliberately OUTSIDE `domain/`. |

## Dependency rule (`docs/architecture/02-dependency-rules.md`)

Direction: `Applications → Control Services → Domain+Application Ports ← Adapters/Plugins`.

- Allowed: `DhanAdapter → BrokerPort`.
- Forbidden: `RiskEngine → DhanAdapter`, `DomainOrder → SQLAlchemy model`, domain importing UI/web frameworks/AI SDKs/storage implementations/broker SDKs.
- Market-specific code never lives in universal `domain/` — that is what `india/` is for.
- Plugin implementations live outside the universal core.

## Ports & adapters pattern

Ports are `@runtime_checkable class X(Protocol):` with `...` bodies and a module docstring stating the boundary. Vendor SDK types and credentials stay outside port modules.

| Port | Path | Adapters |
|---|---|---|
| `BrokerPort` | `ports/broker.py` | `plugins/dhan/adapter.py`, `plugins/reference_broker/adapter.py` |
| `MarketDataPort`, `MarketDataStore` | `ports/market_data.py` | `plugins/dhan/market_data.py`, `persistence/sqlite/market_data.py` |
| `ExecutionPort`, `LiveExecutionPort` | `execution/ports.py` | `integrations/execution_adapter.py`, `execution/paper/*` |
| `UnitOfWork`, `ReceiptRepository`, `PersistentIdempotencyStore` | `persistence/unit_of_work.py` | `persistence/sqlite/*` |
| `InstrumentRegistry` | `domain/instrument_registry.py` | `india/instrument_catalog.py` |

## Placement rules (`docs/architecture/41-current-package-map.md`)

1. Domain objects contain business concepts and no broker SDK types.
2. Application services coordinate use cases; they do not own market-specific rules.
3. Execution owns normalized execution semantics and safety boundaries.
4. Broker adapters stay under integrations/plugins and must not leak vendor SDK types into the core.
5. Research owns historical-data provenance and replay; it cannot silently modify source evidence.
6. India/global/crypto rules live behind their market/plugin boundaries.
7. Infrastructure (persistence, messaging, config, observability) sits behind stable boundaries.
8. **A new module gets its own subpackage when it has independent invariants, tests, or a likely plugin boundary.**
9. **Never create one giant `utils.py`, `services.py`, or `models.py` for unrelated concerns.**
10. Place new functionality in the **smallest coherent package**.

## Structural rules (`docs/architecture/40-package-organization-and-module-boundaries.md`)

- One bounded responsibility per package; ports separate from adapters where practical.
- Tests mirror the source package hierarchy.
- Compatibility shims are temporary and clearly named (existing shims: `research/data_quality.py`, `research/venue_adapters.py`, `execution/market_data.py`, `execution/market_ports.py`). New code uses target boundaries directly.
- Migration principle: existing files are moved/split when next modified — no risky repo-wide renames.
- Avoid repository-wide structural migrations while execution-integrity work is active.
- Deliberately distinct modules that must NOT be merged: `execution/order_lifecycle.py` vs `execution/receipts/lifecycle.py`.

## Design method (contract-gap approach)

1. State the problem as a contract gap.
2. Identify the current owner of the responsibility.
3. Identify consumers and compatibility constraints (search all usages of changed types/fields).
4. Define the smallest contract extension or new boundary.
5. Define invariants and forbidden states.
6. Define evidence/provenance requirements.
7. Define migration/compatibility strategy.
8. Define tests before implementation.
9. Identify deferred concerns explicitly.

Principles: start from existing repository boundaries; one responsibility gets one canonical abstraction; prefer ports/interfaces at the boundary and concrete implementations in the correct module; keep domain semantics independent of brokers and infrastructure; keep India-specific behavior out of universal domain contracts; keep analytics/product surfaces out of core unless explicitly justified; preserve deterministic, fail-closed, evidence-driven behavior.

## Design red flags — reject designs that

- add a second implementation of an existing responsibility;
- move broker logic into core;
- silently infer missing market/account evidence;
- mix simulation assumptions with live truth;
- use strings or booleans as weak authority signals when a typed contract can provide authority;
- change multiple control-path layers without explicit justification.

## Naming conventions

- Modules `snake_case`; classes `PascalCase` with role suffixes: `*Port`, `*Adapter`, `*Registry`, `*Service`, `*Runtime`, `*Reconciler`, `*Snapshot`, `*Result`, `*Decision`, `*Policy`, `*Store`.
- Value objects: `@dataclass(frozen=True, slots=True)`, `value: str`, `__post_init__` validation raising `ValueError` with a lowercase message (e.g. `"plugin id must not be empty"`).
- Enums: `StrEnum` for wire-stable values.
- Errors subclass `quantx.domain.errors.QuantXError`.
- Use `from __future__ import annotations` in every module; line length 100; `mypy --strict`.

## Canonical lifecycle

```
Strategy → TradeIntent → Risk → Policy → ApprovedExecutionRequest
  → Execution Environment → ExecutionReceipt → Fill → Position → Portfolio
```

## Canonical event pattern

`domain/events.py`: `DomainEvent` is `@dataclass(frozen=True, slots=True)` requiring tz-aware `occurred_at` and non-empty `event_id`/`correlation_id`. `domain/event_bus.py` is a synchronous in-process `EventBus` (`subscribe`, `publish`, `clear()` for test isolation).
