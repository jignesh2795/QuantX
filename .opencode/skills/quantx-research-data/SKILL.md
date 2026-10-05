---
name: quantx-research-data
description: Use when working on QuantX historical data, ingestion, datasets, data quality, provenance, point-in-time rules, replay, event replay, experiments, market data storage, candles/quotes, rolls, adjustments, or backtest data. Front-load keywords: research, historical, ingestion, dataset, quality, provenance, replay, point-in-time, candle, OHLCV, backtest data, market data store.
---

# QuantX Research & Market Data

`src/quantx/research/` owns historical-data provenance and replay. Invariant: **research cannot silently modify source evidence** and never fabricates data.

## Module map

| Concern | Path |
|---|---|
| Ingestion | `research/ingest.py`, `research/market_data_ingestion.py` (Port → Store bridge) |
| Dataset catalog | `research/dataset.py`, `dataset_catalog.py`, `dataset_access.py` |
| Quality gate (**authoritative**) | `research/quality.py` — structural usability vs completeness evidence; `UNKNOWN` when no expected timestamps supplied |
| Quality (compat shim) | `research/data_quality.py` — temporary shim, not the target boundary |
| Provenance / integrity | `research/provenance.py`, `research/integrity.py`, `research/artifacts.py` |
| Point-in-time | `research/point_in_time.py` (+ `docs/architecture/40-point-in-time-market-rules.md`) |
| Replay | `research/replay.py`, `research/event_replay.py`, `research/lifecycle.py` |
| Calendar / rules | `research/calendar.py`, `market_rules.py`, `broker_rules.py`, `research_policy.py` |
| Rolls / adjustments | `research/rolls.py`, `research/adjustments.py` |
| Experiments / results | `research/experiments.py`, `research/result.py` |
| Orchestration / storage | `research/orchestrator.py`, `research/storage.py` |
| Venue adapters (compat shim) | `research/venue_adapters.py` |

## Market data contracts

- Canonical types: `domain/market_data.py` → `Quote`, `Candle`, `MarketDataEvent`, `MarketDataType`.
- Ports: `ports/market_data.py` → `MarketDataPort` (source) + `MarketDataStore` (persistence).
- `MarketDataStore` guarantees: deterministic retrieval, **exact-match instrument**, **inclusive bounds**, chronological order, never fabricates or overwrites rows.
- SQLite impl: `persistence/sqlite/market_data.py` (schema **v3**). **Decimals stored via `str()` — never binary float.**
- Dhan market data adapter is **snapshot-only**; streaming subscribe/unsubscribe fail closed.

## Non-negotiable rules

- The engine **never invents a missing value** — absent data fails closed (`UNKNOWN`, not a guess).
- **Canonical payload**: historical research data preserves the canonical OHLCV payload, timeframe, identity, timestamps, and evidence. Do not synthesize bid/ask or silently project richer data into close-only forms.
- **Quality distinctions**: structural quality / completeness / calendar coverage / unknown coverage / invalid-conflicting observations are separate verdicts. Do not infer completeness from gaps when no explicit expected coverage is supplied (`research/quality.py` returns UNKNOWN in that case).
- **Point-in-time**: no future observation may influence an earlier timestamp. Calendar semantics are data-driven; overnight/weekend/holiday intervals use the canonical calendar (`research/calendar.py`), never ad-hoc exclusions.
- **Provenance**: preserve dataset/rule/model identity, version, source, observation time, and selection time wherever the distinction affects auditability (`research/provenance.py`, `research/point_in_time.py`).
- Dataset duplicates: idempotent duplicate vs conflicting duplicate are distinct outcomes (`DatasetCatalog`).
- Rolls are policy-driven (`ContractRollRule`); never silently switch contracts or manufacture a roll price.
- Adjustments and provenance records are append-only evidence — source data is never mutated in place.
- Explicitly-labeled compatibility shims (`research/data_quality.py`, `research/venue_adapters.py`) — new code should use target boundaries (`quality.py`, direct ports).

## Architecture docs

- Research integrity: `docs/architecture/` files 18, 36, 37, 39, 40-point-in-time.
- Testing/backtest contracts: `docs/architecture/11-testing-and-contracts.md`.

## Testing

```powershell
uv run pytest tests/unit/research -q
uv run pytest tests/unit/persistence -q     # market_data store contracts
uv run pytest tests/unit/application/test_backtest.py -q
```
