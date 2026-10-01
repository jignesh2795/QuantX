# QuantX Package Organization and Module Boundaries

## Purpose

QuantX uses small, purpose-specific packages rather than placing unrelated responsibilities in one folder. Directory structure is part of the architecture: a developer should be able to locate a concept without reading a large catch-all module.

## Rules

1. One bounded responsibility per package.
2. Interfaces/ports live separately from concrete adapters where practical.
3. Market-specific code never lives in universal domain packages.
4. India and global market integrations are separated from the beginning.
5. Broker/account state is separate from execution mechanics.
6. Research data, replay, provenance, and experiment management are separate packages.
7. Tests mirror the source package hierarchy.
8. Plugin implementations live outside the universal core.
9. Compatibility shims are temporary and clearly named.
10. Large modules should be split once a responsibility can be named independently.

## Target high-level structure

```text
src/quantx/
├── domain/                 # broker-neutral business objects and value objects
│   ├── instruments/
│   ├── markets/
│   ├── accounts/
│   └── orders/
│
├── application/            # use cases/orchestration
│   ├── trading/
│   ├── research/
│   └── reconciliation/
│
├── execution/              # execution contracts and execution mechanics
│   ├── ports/
│   ├── models/
│   ├── paper/
│   ├── lifecycle/
│   └── accounting/
│
├── portfolio/              # positions, balances, valuation, P&L
│   ├── positions/
│   ├── balances/
│   ├── valuation/
│   └── reconciliation/
│
├── risk/                   # pre-trade and portfolio risk
│   ├── policies/
│   ├── limits/
│   └── checks/
│
├── research/               # historical/research system
│   ├── datasets/
│   ├── ingestion/
│   ├── quality/
│   ├── calendars/
│   ├── lifecycle/
│   ├── events/
│   ├── adjustments/
│   ├── replay/
│   ├── provenance/
│   ├── experiments/
│   ├── artifacts/
│   └── storage/
│
├── integrations/           # account/broker integration contracts
│   ├── accounts/
│   ├── brokers/
│   ├── routing/
│   ├── health/
│   └── reconciliation/
│
├── plugins/                 # concrete replaceable integrations
│   ├── india/
│   │   ├── nse/
│   │   ├── bse/
│   │   └── mcx/
│   ├── global/
│   │   ├── nyse/
│   │   ├── nasdaq/
│   │   └── cme/
│   └── crypto/
│       ├── binance/
│       └── delta/
│
├── ai/                     # AI/ML agents and model services
│   ├── agents/
│   ├── models/
│   ├── features/
│   └── inference/
│
└── infrastructure/         # technical implementations
    ├── persistence/
    ├── messaging/
    ├── observability/
    ├── configuration/
    └── secrets/
```

## Migration principle

The current implementation may temporarily contain several concepts together because the work is incremental. New code should use the target boundaries. Existing files should be moved/split when they are next modified, rather than performing a risky repository-wide rename without tests.

For example:

```text
Current:
src/quantx/execution/paper.py

Target:
src/quantx/execution/paper/engine.py
src/quantx/execution/paper/fills.py
src/quantx/execution/paper/slippage.py
```

Likewise:

```text
Current:
src/quantx/research/quality.py

Target:
src/quantx/research/quality/gates.py
src/quantx/research/quality/report.py
```

The intent is clarity, not directory depth for its own sake. A package is created when it gives a meaningful architectural boundary.
