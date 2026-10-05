---
name: quantx-strategy-plugins
description: Use when writing or registering strategies, Strategy IR, strategy runtime evaluation, StrategyContext, signal/intent validation, strategy registry, or building plugin kinds (broker/market-data/research/risk) in QuantX. Front-load keywords: strategy, StrategyIR, signal, intent, on_market_data, registry, plugin, factory, descriptor.
---

# QuantX Strategy & Plugin APIs

## Strategy stack

```
StrategyDefinition → StrategyCompiler → StrategyIR → StrategyRegistry.resolve() → ExecutableStrategy
  → StrategyRuntime.evaluate() → StrategyEvaluationService → StrategyExecutionDecision
  → StrategyExecutionPreparation (risk + policy) → ApprovedExecutionRequest
```

The preparation step deliberately **stops before broker/paper execution** so all execution modes share identical semantics.

### StrategyIR (`strategy/ir.py`)

- `StrategyIR(strategy_id, version, name, market_contexts, parameters)`.
- Parameters are a **sorted, unique** tuple of `(str, str)` pairs — deterministic, hashable.
- Contains no broker/runtime/execution state.

### ExecutableStrategy (`strategy/runtime.py`)

A `Protocol` with one method:

```python
def on_market_data(self, context: StrategyContext) -> StrategyResult: ...
```

### StrategyContext (`strategy/context.py`)

`StrategyContext(event: MarketDataEvent, ir: StrategyIR)` — contains **no execution-mode or broker state**.

### Runtime validation (`strategy/runtime.py`)

`StrategyRuntime.evaluate(event, ir)` enforces:

- Signal id/version/instrument must match the IR and the event.
- `HOLD` cannot carry an intent.
- BUY signal ⇒ BUY intent (and vice versa).

### Registration (`strategy/registry.py`)

```python
StrategyRegistry.register(strategy_id, version, factory)  # duplicate → ValueError
instance = StrategyRegistry.resolve(ir)                    # fresh instance each call; unknown → KeyError
```

`StrategyFactory = Callable[[], ExecutableStrategy]`.

### Reference implementation

`strategy/reference.py` → `BuyAndHoldStrategy`.

## Plugin API (`plugins/registry.py`)

- `PluginKind`: `BROKER`, `MARKET_DATA`, `STRATEGY`, `RESEARCH`, `RISK`, `UI`.
- `PluginDescriptor(plugin_id, name, version, kind, capabilities, market_contexts)`.
- `PluginFactory` is a `Protocol` — `__call__() -> object`.
- Lifecycle: `DISCOVERED → ENABLED → READY / DEGRADED / DISABLED / FAILED`.

```python
registry.register(descriptor, factory)  # duplicate ID raises
registry.get(id); registry.list(kind)
registry.enable(id); registry.mark_ready(id)
registry.mark_degraded(id, reason); registry.mark_failed(id, reason)
registry.disable(id)
obj = registry.create(id)               # only from ENABLED or READY
```

Rules:

- Registration is **explicit, in-process** — no `pyproject` entry-point discovery exists yet.
- Descriptor stores metadata + factory only. **Secrets/credentials never go in the registry.**
- Registration helpers live in each plugin's `__init__.py` (e.g. `register_dhan_broker`).

## Testing

```powershell
uv run pytest tests/unit/strategy -q     # ir, compiler, registry, runtime, evaluation, deployment, execution, reference
uv run pytest tests/unit/plugins -q      # registry + dhan/reference adapters
```
