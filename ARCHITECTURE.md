# QuantX Architecture

QuantX is currently a local-first Python library for deterministic trading infrastructure, with a market-neutral universal core and India as its first and only fully implemented market. It is not a production CLI, cloud service, distributed runtime, UI/Flow authoring system, or AI-agent platform.

## Scope (ADR-008)

The v0.1 scope is a programmatic local-first library:

- deterministic domain, execution, recovery, and accounting primitives;
- paper/replay/shadow execution with explicit market data;
- SQLite-backed persistence and recovery;
- broker and market-data adapters behind ports;
- optional Dhan plugin support;
- India market rules and charges only where implemented.

Other market modules remain future work; digital assets is a placeholder. No multi-currency or FX conversion is implemented. See [ADR-008](docs/architecture/adr/ADR-008-v0.1-programmatic-library-scope.md).

## Boundaries

- `src/quantx/domain`: canonical orders, instruments, risk, execution requests, accounting and value objects. No broker SDKs or web frameworks.
- `src/quantx/application`: orchestration, recovery, execution admission, and strategy preflight.
- `src/quantx/execution`: broker ports, paper venue, idempotency, receipts, quarantine, and execution lifecycle.
- `src/quantx/persistence`: SQLite storage and unit-of-work boundaries.
- `src/quantx/integrations`: account/connection registry and broker adapter integration.
- `src/quantx/plugins`: optional broker plugins, including Dhan transport and host composition.
- `src/quantx/markets`: market-neutral module contracts and the implemented India module.
- `src/quantx/markets/digital_assets`: interface-only placeholder; not a crypto implementation.
- `src/quantx/strategy`, `research`, and backtest modules: implemented only where present in source and tests.

## Order lifecycle and safety path

QuantX uses one canonical order lifecycle and fail-closed admission. For the ordered control path, see [Control and safety path](docs/architecture/control-and-safety-path.md); for implemented behavior and current limitations, see [Status](docs/STATUS.md).

Unsupported, malformed, or uncertain outcomes remain explicit (`UNKNOWN` or blocked). Recovery never submits broker orders.

## Adapter boundaries

- Broker and market-data adapters implement ports in `src/quantx/execution/ports.py` and `src/quantx/ports`.
- Concrete broker SDKs are confined to plugin transport modules.
- Capability and descriptor results are exact-type validated before use.

## Strategy, research, backtest, and paper

- Strategy compilation and replay exist in `src/quantx/strategy` and `src/quantx/application/backtest.py`.
- Paper execution is deterministic and requires explicit market snapshots.
- Research, backtest, and paper select market behavior through explicit `MarketContext`.
- Backtest and paper share execution semantics where implemented.
- LIVE dispatch remains India-only and blocked by risk-evidence and recovery prerequisites.

## Limitations

- No production-ready CLI.
- No cloud deployment or distributed runtime.
- No multi-currency or FX conversion.
- No production LIVE readiness claim.
- No real-broker end-to-end support claim.
- No UI, Flow authoring, scheduling, or AI-agent functionality.
- Dhan LIVE risk evidence remains blocked until authoritative account-level evidence is available.

## Authoritative references

- [Architecture overview](docs/architecture/README.md)
- [Architecture records](docs/architecture/00-overview.md)
- [ADR index](docs/architecture/adr/)
- [ADR-008 scope](docs/architecture/adr/ADR-008-v0.1-programmatic-library-scope.md)
- [Acceptance criteria](docs/architecture/28-v0.1-acceptance-criteria.md)
- [Control and safety path](docs/architecture/control-and-safety-path.md)
- [Historical LIVE safety audit](docs/architecture/56-live-execution-safety-audit-and-priority.md)
- [Implementation guide](docs/implementation/README.md)
- [Roadmap](docs/roadmap/README.md)
- [Status](docs/STATUS.md)
- [Contributing](CONTRIBUTING.md)
