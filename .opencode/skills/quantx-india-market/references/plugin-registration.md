# Plugin Registration & Reference Broker (quantx-india-market)

## Plugin registry

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

## Reference broker

`src/quantx/plugins/reference_broker/` — `ReferenceBrokerAdapter` + `InMemoryReferenceBrokerTransport` for adapter conformance; advertises `PAPER_TRADING` capability. Use it for tests instead of Dhan.
