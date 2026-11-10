# Getting Started

This guide takes you from a fresh checkout to a deterministic, offline paper-execution example. It does not connect to a broker or submit a real order.

## Requirements

- Python **3.12**.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python and dependency management.
- Git and a checkout of the QuantX repository.

The pinned Python version is recorded in `.python-version`, and `uv.lock` records the dependency set.

## 1. Prepare the environment

From the repository root:

```bash
uv python install
uv sync --dev --locked
```

On Windows, `.\scripts\setup.ps1` performs the interpreter installation and default development sync when uv is installed.

## 2. Run the offline paper example

```bash
uv run python examples/paper_smoke.py
```

The example uses QuantX's deterministic in-memory `PaperBroker` and a synthetic bid/ask/last snapshot. It requires no broker account, credentials, network connection, market data, or external service. It prints a `paper smoke: OK` line and the resulting match/evidence details.

This is an executable example of the paper component only. It does not prove broker integration, exchange connectivity, production behavior, or LIVE readiness.

## 3. Run tests

Run the focused paper-execution tests:

```bash
uv run pytest tests/unit/execution/paper
```

Run the complete default test suite:

```bash
uv run pytest
```

The project configures pytest's quiet mode in `pyproject.toml`; do not add a second `-q` when collecting validation counts.

To work on the optional Dhan adapter, install its SDK extra and run the Dhan tests:

```bash
uv sync --dev --extra dhan --locked
uv run pytest tests/unit/plugins/dhan
```

Dhan-extra installation does not authorize or require connecting to a broker. Tests should use deterministic fakes unless a separately authorized task explicitly establishes a safe, non-production requirement.

## 4. Understand the architecture

Read these documents in order:

1. [Architecture overview](architecture/00-overview.md).
2. [Global market separation](architecture/32-global-market-separation.md).
3. [Current package map](architecture/41-current-package-map.md).
4. [Control and safety path](architecture/control-and-safety-path.md).
5. [Current status and validation baseline](STATUS.md).

The universal core is market-neutral by design. India is the only implemented market module. Digital assets is a placeholder, not an implemented crypto market. QuantX does not currently provide FX or multi-currency conversion.

## What is not included

- No production-ready CLI; the CLI remains deferred.
- No hosted or distributed runtime.
- No implemented US, EU, UK, APAC, or crypto market module.
- No production LIVE readiness claim. LIVE execution remains India-only and blocked by the risk-evidence gate.

For development conventions and pull-request evidence requirements, read [Contributing](../CONTRIBUTING.md).
