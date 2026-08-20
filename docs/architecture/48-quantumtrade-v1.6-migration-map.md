# QuantumTrade v1.6 → QuantX migration map

## Purpose

QuantumTrade v1.6 is the existing functional codebase. QuantX is the target architecture and contract layer. This document prevents reimplementation of functionality that already exists and defines where existing responsibilities belong in QuantX.

## Source inventory

The v1.6 repository contains 257 Python source files outside `.git`, plus tests, API, frontend CLI, infrastructure, adapters, strategies, indicators, AI placeholders, and research/backtesting functionality. The source tree is organized primarily under `core/`, `modules/`, `adapters/`, `api/`, `application/`, `infra/`, `frontend/`, `ai/`, and `tests/`.

## Core mapping

| QuantumTrade v1.6 | QuantX target | Action |
|---|---|---|
| `core/time/*` | `domain/clock.py` | ADAPT/MERGE |
| `core/events/*` | `domain/events.py`, `domain/event_bus.py` | ADAPT/MERGE |
| `core/contracts/market_snapshot.py` | `execution/market_data.py` + domain market contracts | ADAPT |
| `core/contracts/trade_intent.py` | `domain/order_intents.py` | ADAPT |
| `core/contracts/strategy_result.py` | strategy/application result contracts | ADAPT |
| `core/order/*` | `domain/orders.py`, `domain/execution_request.py`, `execution/order_lifecycle.py` | MERGE by responsibility |
| `core/position/*` | `domain/positions.py` | ADAPT |
| `core/wallet/*` | `domain/accounts.py`, portfolio/accounting boundaries | ADAPT |
| `core/risk/*` | `domain/risk.py` + `execution/preconditions/` | SPLIT by responsibility |
| `core/capital/*` | `domain/allocation.py`, `domain/risk.py`, application policy | ADAPT |
| `core/portfolio/*` | `domain/portfolio.py` | ADAPT |
| `core/execution/execution_engine.py` | `execution/paper.py` | ADAPT, preserve behavior |
| `core/backtest/*` | `research/replay.py`, research orchestration/result | ADAPT |
| `core/optimization/*` | `research/experiments.py`, optimization subsystem to be added under research | ADAPT |
| `core/robustness/*` | `research/experiments.py` and dedicated research modules as needed | ADAPT |
| `core/analytics/*` | research/result + analytics layer | ADAPT |
| `modules/strategies/*` | strategy subsystem | MIGRATE, do not rewrite |
| `modules/indicators/*` | strategy/features/indicators subsystem | MIGRATE |
| `modules/backtesting/*` | research | MERGE/ADAPT; avoid duplicate backtest engines |
| `modules/data/*` | `research/data.py`, ingestion/storage | ADAPT |

## Integration mapping

| QuantumTrade v1.6 | QuantX target | Action |
|---|---|---|
| `adapters/exchange/exchange_adapter.py` | `integrations/brokers.py` / broker port | ADAPT |
| `adapters/exchange/binance_adapter.py` | crypto Binance plugin/adapter | MIGRATE behind boundary |
| `adapters/exchange/mock_adapter.py` | paper/test adapter | ADAPT |
| `adapters/exchange/models.py` | integration DTOs; do not leak into domain | ADAPT |
| `adapters/live/live_trading_engine.py` | live execution/application orchestration | ADAPT |
| `adapters/live/market_data_feed.py` | market-data integration | ADAPT |
| `adapters/live/order_synchronizer.py` | `integrations/reconciliation/orders.py` | MERGE |
| `adapters/safety/live_safety_monitor.py` | risk/execution safety boundary | ADAPT |
| `adapters/broker_facade.py` | integrations/application boundary | ADAPT; remove facade leakage |
| `infra/reconciler.py` | `integrations/reconciliation/` | MERGE |
| `infra/persistence/state_store.py` | infrastructure persistence | ADAPT |

## Application/API mapping

| QuantumTrade v1.6 | QuantX target | Action |
|---|---|---|
| `application/bot_session.py` | application/orchestration/session | ADAPT; preserve orchestration-only rule |
| `application/trading_service.py` | application/trading | ADAPT |
| `api/rest/*` | QuantX API/application boundary | MIGRATE after core stabilization |
| `api/websocket/*` | event-stream/API layer | MIGRATE after core stabilization |
| `frontend/cli/*` | CLI/application presentation | MIGRATE later |

## Research mapping

| QuantumTrade v1.6 | QuantX target | Action |
|---|---|---|
| `core/backtest/*` | research replay/orchestration | MERGE |
| `modules/backtesting/*` | research | MERGE; one canonical engine |
| `core/optimization/*` | research experiments/optimization | ADAPT |
| `core/robustness/*` | research robustness | ADAPT |
| `core/analytics/*` | research result/analytics | ADAPT |
| `modules/data/*` | research data/ingestion | ADAPT |

## Safety and correctness migration rules

1. Do not carry `RiskConfig.min_notional` as a global capital assumption. A venue minimum is valid only when supplied by an explicit venue/broker rule.
2. Do not carry a hard-coded default paper/live balance into QuantX. Live capital must come from observed account state; paper capital must be explicitly configured.
3. Preserve the existing separation where execution does not directly mutate wallet/position state; route through accounting/portfolio boundaries.
4. Preserve deterministic clock injection for paper/replay tests.
5. Existing Binance adapter behavior must remain behind an integration/plugin boundary; vendor DTOs must not become domain types.
6. Historical/backtest modules must be merged with QuantX's point-in-time, quality, provenance, adjustment, roll, and replay contracts rather than bypassing them.
7. `UNKNOWN` broker/account/position state must never become execution `READY` implicitly.
8. Existing strategies and indicators are valuable implementation assets and should be migrated before recreating equivalent strategies.
9. The v1.6 API/session architecture should be reused; do not build a second independent trading orchestration path.
10. The ZIP/RAR snapshots are source evidence; claims about test counts or runtime behavior are not treated as independently verified until executed in the current environment.

## Migration order

1. Inventory and map existing v1.6 modules.
2. Migrate domain primitives and contracts.
3. Migrate order/risk/wallet/position/execution behavior.
4. Migrate paper execution and accounting.
5. Migrate Binance through the new integration boundary.
6. Migrate research/backtesting/optimization/robustness as one research stack.
7. Migrate strategies and indicators.
8. Migrate persistence and reconciliation.
9. Migrate API/WebSocket/session control.
10. Run the full test suite and remove only confirmed duplicate legacy implementations.
11. Reconcile the QuantX branch with `main` after the migration baseline is tested.

## Non-goals

- Do not rewrite working QuantumTrade functionality merely to make filenames look cleaner.
- Do not introduce a second implementation when an existing QuantumTrade implementation can be adapted.
- Do not expand QuantX architecture until the corresponding existing functionality has been mapped.
