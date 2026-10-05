---
name: quantx-india-market
description: Use when working on India-market specifics in QuantX — Indian exchanges/segments, F&O contracts, order validity rules, IST session calendar, instrument catalog, Dhan broker plugin, Dhan SDK, option/futures specs, price bands, rolls, lot sizes. Front-load keywords: India, Indian, Dhan, F&O, futures, options, expiry, strike, IST, session, exchange, NSE, BSE, lot size, broker.
---

# QuantX India Market & Broker Plugins

Market-specific rules live in `src/quantx/india/` — **never in universal `domain/`**. Rules are **data, not code**: absent or incoherent rule data fails closed; the engine never invents a missing value.

## India domain (`src/quantx/india/`)

| Module | Contents |
|---|---|
| `domain.py` | `IndianExchange`, `IndianSegment` (`EQ`, `FO`, `CD`, `COM`), `ProductType` (`CNC`, `MIS`, `NRML`, `DELIVERY`), `IndianInstrumentSpec`, `OptionContractSpec` |
| `execution_rules.py` | Deterministic order-validity checks: **exact `Decimal` only** (floats/NaN/inf/bools rejected), fixed check order, stable machine-readable failure codes |
| `rule_data.py` | Versioned venue rule snapshots — `PriceBandRuleSnapshot`, allowed order-type/TIF/product sets with version/provenance/effective time (**rules as data**) |
| `session_calendar.py` | `ZoneInfo`-based IST calendar → `IndiaSessionPermission` (ORDER_SUBMISSION / MODIFICATION / CANCELLATION) → `IndiaSessionDecision` ALLOW/BLOCK |
| `instrument_catalog.py` | `IndianInstrumentCatalog` implements `InstrumentRegistry` — resolves, never manufactures metadata |
| `historical.py` | `IndianHistoricalOHLCVNormalizer` |

F&O spec enforcement in `IndianInstrumentSpec.to_instrument()` / `to_contract()`:

- Derivatives require tz-aware expiry + underlying.
- Futures must NOT define strike/option_type; options MUST.

Core (market-neutral) F&O primitives are in `domain/instruments.py`: `Contract` (underlying, expiry, strike, option_type CALL/PUT), `Instrument.lot_size` / `multiplier` / `tick_size`, `MarketFamily.DERIVATIVES`.

## Evidence rules (India rule data)

Never type current exchange/broker facts from memory. For market data and venue rules require:

- explicit version;
- source/provenance;
- retrieval/effective timestamps where applicable;
- timezone-aware values;
- deterministic selection;
- explicit missing/unknown behavior.

**Never invent:** lot sizes, freeze quantities, price bands, holidays, special sessions, brokerage/tax/charge rates, contract multipliers. Unknown or incoherent India rule data fails closed.

Keep these responsibilities separate — do not merge them into one catch-all engine:

1. universal order validation (core);
2. India-specific product/venue compatibility (`execution_rules.py`);
3. session/calendar policy (`session_calendar.py`);
4. versioned rule-data loading (`rule_data.py`).

## Dhan broker plugin (`src/quantx/plugins/dhan/`)

The only real broker adapter. Optional SDK extra installed via `uv sync --dev --extra dhan`. The Dhan SDK version is whatever the repository's current dependency configuration specifies; verify `pyproject.toml`/`uv.lock` before making dependency claims.

- `transport.py` — **the ONLY module in the repo allowed to import `dhanhq`**. Defines `DhanTransport` Protocol, `DhanSDKTransport`, `InMemoryDhanTransport`, `DhanTimeoutError`.
- `adapter.py` — `DhanBrokerAdapter(BrokerPort)`; independently enforces account-scoped connection before submit/cancel/reconcile.
- `market_data.py` — `DhanMarketDataAdapter(MarketDataPort)`; snapshot-only; `subscribe()`/`unsubscribe()` **fail closed** (no async streaming in the architecture).
- `capabilities.py` — `DHAN_CAPABILITIES = {ORDER_SUBMISSION, ORDER_CANCELLATION, BALANCES, POSITIONS, MARKET_DATA}`.
- `mapping.py` — order types: MARKET→MARKET, LIMIT→LIMIT, STOP→STOP_LOSS_MARKET, STOP_LIMIT→STOP_LOSS; only `DAY`/`IOC` TIF accepted (`GTC`/`FOK` rejected); 30-char hex Dhan correlation ID derived deterministically from the QuantX correlation ID.
- `recovery.py` — `DhanRecoveryEvidenceProvider` (read-only; never submits).
- `host.py` — `build_dhan_host_runtime()` (deployment composition only; no broker-submit surface).
- `models.py` — `DhanCredentials`, request/response models — **kept outside the core domain**.
- `mapping.py`/`recovery.py` never leak SDK types into core modules.

Operational prerequisite: Dhan requires **static IP whitelisting** (external to the adapter — do not attempt to bypass in code).

Uncertain broker outcomes → `UNKNOWN` receipt, **no automatic retry** — reconciliation resolves it.

## Reference broker

`src/quantx/plugins/reference_broker/` — `ReferenceBrokerAdapter` + `InMemoryReferenceBrokerTransport` for adapter conformance; advertises `PAPER_TRADING` capability. Use it for tests instead of Dhan.

## Plugin registration

`src/quantx/plugins/registry.py` — explicit in-process `PluginRegistry` (no entry-point discovery):

```python
registry.register(descriptor, factory)   # duplicate plugin_id raises
registry.enable(id); registry.mark_ready(id)
instance = registry.create(id)           # only from ENABLED/READY
```

- `PluginKind`: BROKER, MARKET_DATA, STRATEGY, RESEARCH, RISK, UI.
- Lifecycle: `DISCOVERED → ENABLED → READY / DEGRADED / DISABLED / FAILED`.
- Descriptor carries metadata + factory only — **secrets/credentials never go in the registry**.
- Helpers: `register_dhan_broker(registry, factory)` in `plugins/dhan/__init__.py`; `REFERENCE_BROKER_DESCRIPTOR` in `plugins/reference_broker/__init__.py`.

## F&O rolls (research side)

`src/quantx/research/rolls.py` — `ContractRollRule`, `ContractRollEvent`, `RollMethod`: policy-driven; never silently switches contracts or manufactures a roll price.

## Testing

```powershell
uv run pytest tests/unit/india -q
uv run pytest tests/unit/plugins/dhan -q
uv run pytest tests/unit/integrations -q
```
