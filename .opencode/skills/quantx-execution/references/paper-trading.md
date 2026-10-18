# Paper Trading (quantx-execution)

> Cash/valuation/P&L/charges knowledge lives in `quantx-simulation-accounting`; this reference covers submission and venue semantics only.

Three layers:

1. `execution/paper/` — deterministic venue: `broker.py` (`PaperBroker`), `matching.py` (`PaperMatcher`), `fills.py`, `latency.py`, `order_types.py`, `profile.py`, `evidence.py`, `executor.py`.
2. `execution/paper_engine.py` — legacy flat `PaperExecutionEngine` (re-exported from `execution/paper/__init__.py`).
3. `execution/paper_session.py` — session orchestration: cash ledger + margin ledger + mark-to-market + post-trade enforcement.

App-level: `application/backtest.py` → `DeterministicBacktestService` composes replay + strategy + risk + policy + paper execution + accounting.

Paper contract: **missing required quotes never create invented fills**; repeated client order IDs are idempotent. `PaperMatcher` "never invents market data".
