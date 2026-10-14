# QuantX

Open-source, modular, event-driven trading infrastructure and platform for Indian markets.

## Status

V0.1 acceptance is complete for the declared programmatic local-first library scope under ADR-008; the CLI remains explicitly deferred. M4.1 deterministic strategy-to-paper rehearsal merged on 2026-10-14 via PR #218 (validated feature head `d99c12f3ae051f992722bee2bc8ea3253032fdc8`; merge commit `a0bf101b6f6bb87d11460cefb199932a768d6335`).

The current implementation sequence is post-v0.1 Strategy Platform work. The next ordered design task is issue #197 (market-pack pre-trade-check pipeline), which precedes broader engine-truth `StrategyContext` and deterministic callback work in issue #196. Overall M4 remains in progress: Python/Flow runtime parity remains the M4 exit criterion. Execution/recovery boundaries stay frozen unless a concrete invariant violation is reproduced. UI/Flow authoring, AI/agents, scheduling, broad CLI work, and distributed services remain outside M4.1.

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
