# QuantX

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/badge/Code%20style-Ruff-261230.svg)](https://docs.astral.sh/ruff/)

**Open-source, event-driven trading infrastructure with a market-neutral core and an India-first implementation.**

QuantX is a local-first Python trading library built around deterministic domain contracts, explicit market context, ports-and-adapters, and fail-closed execution boundaries.

## What it is

- A modular monolith for trading, research, backtesting, and paper execution.
- A vendor-neutral core with market-specific behavior isolated under `quantx.markets`.
- An India market module as the **only fully implemented market**.
- A plugin boundary for broker and market-data integrations.

Digital assets is an interface-only placeholder, not a supported crypto implementation. Other regions remain future work. QuantX does not currently provide multi-currency or FX conversion.

## Architecture at a glance

```text
Research / Backtest / Paper
           │ MarketContext
           ▼
    Universal QuantX Core
       ├── Market modules
       │     ├── India (implemented)
       │     └── Digital assets (placeholder)
       └── Broker and data plugins (separate adapter boundary)
```

Research, backtest, and paper are designed to select market behavior from explicit context. LIVE execution remains India-only and is currently blocked by the project's risk-evidence gate.

## Get started

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv python install
uv sync --dev --locked
uv run python examples/paper_smoke.py
```

Run the focused paper-execution tests with `uv run pytest tests/unit/execution/paper`. See [Getting Started](docs/GETTING_STARTED.md) for the complete local workflow.

## Current status

The declared v0.1 programmatic local-first library scope is acceptance-complete. The CLI is deferred. The strategy-platform M4 runtime-parity milestone is complete. Production LIVE readiness is **not** claimed; LIVE dispatch remains blocked. See [current status](docs/STATUS.md) and the [status history](docs/STATUS_HISTORY.md).

## Documentation

- [Get started in five minutes](docs/GETTING_STARTED.md)
- [Architecture map](docs/architecture/README.md)
- [Implementation guide](docs/implementation/README.md)
- [Roadmap](docs/roadmap/README.md)
- [Architecture decisions](docs/decisions/README.md)
- [Research and technology evaluation](docs/research/README.md)
- [Runnable local examples](examples/README.md)

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Security reporting instructions are in [SECURITY.md](SECURITY.md).

QuantX is local-first and contributor-driven. GitHub Actions is not part of the current validation workflow; contributors should report exact local commands and results as described in the repository guides.
