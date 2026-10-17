# Ports & Adapters (quantx-architecture)

Dependency direction: `Applications → Control Services → Domain+Application Ports ← Adapters/Plugins` (`docs/architecture/02-dependency-rules.md`).

Ports are `@runtime_checkable class X(Protocol):` with `...` bodies and a module docstring stating the boundary. Vendor SDK types and credentials stay outside port modules.

| Port | Path | Adapters |
|---|---|---|
| `BrokerPort` | `ports/broker.py` | `plugins/dhan/adapter.py`, `plugins/reference_broker/adapter.py` |
| `MarketDataPort`, `MarketDataStore` | `ports/market_data.py` | `plugins/dhan/market_data.py`, `persistence/sqlite/market_data.py` |
| `ExecutionPort`, `LiveExecutionPort` | `execution/ports.py` | `integrations/execution_adapter.py`, `execution/paper/*` |
| `UnitOfWork`, `ReceiptRepository`, `PersistentIdempotencyStore` | `persistence/unit_of_work.py` | `persistence/sqlite/*` |
| `InstrumentRegistry` | `domain/instrument_registry.py` | `india/instrument_catalog.py` |
