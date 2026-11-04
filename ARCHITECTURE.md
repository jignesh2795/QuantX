# QuantX Architecture

QuantX is currently a local-first Python library for deterministic trading
infrastructure. It is not a production CLI, cloud service, distributed runtime,
UI/Flow authoring system, or AI-agent platform.

## Scope (ADR-008)

The v0.1 scope is a programmatic local-first library:

- deterministic domain, execution, recovery, and accounting primitives;
- paper/replay/shadow execution with explicit market data;
- SQLite-backed persistence and recovery;
- broker and market-data adapters behind ports;
- optional Dhan plugin support;
- India-focused market policies and charges where implemented.

See [ADR-008](docs/architecture/adr/ADR-008-v0.1-programmatic-library-scope.md).

## Boundaries

- `src/quantx/domain`: canonical orders, instruments, risk, execution requests,
  accounting and value objects. No broker SDKs or web frameworks.
- `src/quantx/application`: orchestration, recovery, execution admission, and
  strategy preflight.
- `src/quantx/execution`: broker ports, paper venue, idempotency, receipts,
  quarantine, and execution lifecycle.
- `src/quantx/persistence`: SQLite storage and unit-of-work boundaries.
- `src/quantx/integrations`: account/connection registry and broker adapter
  integration.
- `src/quantx/plugins`: optional broker plugins, including Dhan transport and
  host composition.
- `src/quantx/strategy`, `research`, and backtest modules: implemented only
  where present in source and tests.

## Order lifecycle and safety path

QuantX uses one canonical order lifecycle and fail-closed admission:

1. Approved execution request and policy verification.
2. Trading-gate and session checks.
3. Market-policy and risk checks.
4. Broker connection, health, instrument, and capability probes.
5. Durable idempotency reservation.
6. Broker submission only after all prior checks pass.
7. Receipt persistence, quarantine, and recovery.

Unsupported, malformed, or uncertain outcomes remain explicit (`UNKNOWN` or
blocked). Recovery never submits broker orders.

## Adapter boundaries

- Broker and market-data adapters implement ports in
  `src/quantx/execution/ports.py` and `src/quantx/ports`.
- Concrete broker SDKs are confined to plugin transport modules.
- Capability and descriptor results are exact-type validated before use.

## Strategy, research, backtest, and paper

- Strategy compilation and replay exist in `src/quantx/strategy` and
  `src/quantx/application/backtest.py`.
- Paper execution is deterministic and requires explicit market snapshots.
- Backtest and paper share execution semantics where implemented.
- LIVE dispatch remains gated by risk evidence and recovery prerequisites.

## Limitations

- No production-ready CLI.
- No cloud deployment or distributed runtime.
- No production LIVE readiness claim.
- No real-broker end-to-end support claim.
- No UI, Flow authoring, scheduling, or AI-agent functionality.
- Dhan LIVE risk evidence remains blocked until authoritative account-level
  evidence is available.

## Authoritative references

- [Architecture overview](docs/architecture/README.md)
- [Architecture records](docs/architecture/00-overview.md)
- [ADR-008 scope](docs/architecture/adr/ADR-008-v0.1-programmatic-library-scope.md)
- [Acceptance criteria](docs/architecture/28-v0.1-acceptance-criteria.md)
- [Safety architecture](docs/architecture/56-live-execution-safety-audit-and-priority.md)
- [Implementation guide](docs/implementation/README.md)
- [Roadmap](docs/roadmap/README.md)
- [Status](docs/STATUS.md)
- [Contributing](CONTRIBUTING.md)
PY