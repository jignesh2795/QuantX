# Ports & Adapters (quantx-architecture)

Dependency direction: `Applications → Control Services → Domain+Application Ports ← Adapters/Plugins` (`docs/architecture/02-dependency-rules.md`).

Ports are `@runtime_checkable class X(Protocol):` with `...` bodies and a module docstring stating the boundary. Vendor SDK types and credentials stay outside port modules.

| Port | Path | Adapters |
|---|---|---|
| `BrokerAdapter`, `BrokerCapability`, `BrokerConnectionRef`, `BrokerDescriptor`, `CapabilitySet` | `ports/broker.py` | `plugins/dhan/*`, `plugins/reference_broker/*`, `integrations/brokers.py` (identity shim) |
| `BrokerPort` (receipt-bearing) | `execution/ports.py` | `plugins/dhan/adapter.py`, `plugins/reference_broker/adapter.py` |
| `MarketDataPort`, `MarketDataStore` | `ports/market_data.py` | `plugins/dhan/market_data.py`, `persistence/sqlite/market_data.py` |
| `ExecutionPort`, `LiveExecutionPort` | `execution/ports.py` | `integrations/execution_adapter.py`, `execution/paper/*` |
| `UnitOfWork`, `ReceiptRepository`, `PersistentIdempotencyStore`, `SubmissionQuarantineRepository`, `QuarantineEvidenceReader` | `execution/persistence.py` | `persistence/sqlite/*` (`quantx.persistence` keeps an identity-preserving re-export) |
| `InstrumentRegistry` | `domain/instrument_registry.py` | `india/instrument_catalog.py` |

Ownership rule: a port belongs with the records its methods accept or return.
`BrokerPort.submit/cancel/reconcile` return canonical execution receipts, and
`UnitOfWork.receipts`/`idempotency` are execution repositories, so both live in
`execution/`. `ports/` therefore depends on `domain/` only; it must never import
`execution/`. `ports/persistence.py` and `ports/broker.BrokerPort` are retired —
do not reintroduce them as shims, because a shim importing execution from ports
recreates the package cycle.
