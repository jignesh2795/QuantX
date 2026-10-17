# Dhan Plugin Inventory (quantx-india-market)

`src/quantx/plugins/dhan/` is the only real broker adapter. Optional SDK extra installed via `uv sync --dev --extra dhan`. The Dhan SDK version is whatever the repository's current dependency configuration specifies; verify `pyproject.toml`/`uv.lock` before making dependency claims.

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
