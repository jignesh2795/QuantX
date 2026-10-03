# QuantX

Open-source, modular, event-driven trading infrastructure and platform for Indian markets.

## Status

v0.1 implementation is active. The repository now contains domain, application, execution, research, India-market, integration, plugin, strategy, port, and persistence foundations. The active implementation track is execution integrity, reconciliation, and recovery safety; UI, AI, and broader distributed services remain future capabilities.

## Design direction

QuantX is being designed as a modular monolith first, with a distributed-ready architecture. The core is event-driven and domain-driven, with ports-and-adapters, capability-based broker/data integrations, and a plugin-first ecosystem.

The initial product focus is Indian markets, including equities, futures and options, while keeping the universal trading core market-neutral enough to support additional venues later.

## Current planning baseline

- QuantumTrade v1.6: engineering reference for event-driven trading, execution, safety and session/API design.
- OpenAlgo: Indian broker/platform and control-plane reference.
- Hummingbot: connector and plugin architecture reference.
- NautilusTrader: event-driven, deterministic and adapter-oriented architecture reference.
- Freqtrade, Jesse, LEAN and vectorbt: strategy and research workflow references.

## Planned architectural principles

1. Modular monolith first; distributed-ready later.
2. Minimal, stable core with plugins and adapters around it.
3. Event-driven trading lifecycle.
4. Domain-driven contracts for orders, fills, positions, portfolios, risk and execution.
5. Broker and market-data integrations are adapters, not core dependencies.
6. Capability-based compatibility checks.
7. Backtest, sandbox, paper and live share the same trading semantics.
8. F&O is represented in the domain model from the beginning.
9. UI and AI consume the engine through stable APIs instead of defining the core.
10. Local-first deployment with optional distributed operation.

## Documentation map

The canonical documentation entry points are:

- `docs/STATUS.md` — current implementation and validation baseline.
- `docs/architecture/README.md` — architecture records and current canonical boundaries.
- `docs/implementation/README.md` — implementation discipline and build sequence.
- `docs/roadmap/README.md` — future milestones and decision gates.
- `docs/decisions/README.md` — durable architecture decisions.
- `docs/research/README.md` — external-project research and technology evaluation.

The project follows research → compare → decide → document → build.

## Windows development with uv

QuantX uses **uv** as its canonical Python environment and dependency manager. The project is pinned to Python 3.12 via `.python-version`; uv can install the pinned interpreter when it is not already available. uv supports Windows and project environments directly.

Install uv on Windows, for example with WinGet:

```powershell
winget install --id=astral-sh.uv -e
```

From the repository root:

```powershell
.\scripts\setup.ps1
uv run pytest -q
```

Or run the setup steps directly:

```powershell
uv python install
uv sync --dev
uv lock
uv run pytest -q
```

The Dhan SDK is an optional extra. The suite passes without it (the one
SDK-dependent test skips itself), but install it if you work on the Dhan
plugin:

```powershell
uv sync --dev --extra dhan
```

To keep changed-file Ruff errors out of pushes, enable the repo's hook:

```powershell
git config core.hooksPath scripts/hooks
```

Useful local checks:

```powershell
uv run pytest tests/unit/execution/paper -q
uv run python scripts/test_execution.py
uv run python scripts/test_fast.py
uv run python scripts/test_all.py
```

After dependency changes, regenerate the lockfile with `uv lock` and commit `uv.lock` so the environment is reproducible. uv's project workflow uses `uv sync` and `uv run`, with development dependencies defined in the `dev` dependency group.
