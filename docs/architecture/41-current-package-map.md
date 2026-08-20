# QuantX Current Package Map

Target organization for the modular core. New functionality should be placed in the smallest coherent package rather than accumulating in catch-all files.

```text
src/quantx/
├── domain/
│   ├── instruments/
│   ├── markets/
│   ├── accounts/
│   └── orders/
├── application/
│   ├── commands/
│   ├── queries/
│   ├── workflows/
│   └── services/
├── execution/
│   ├── ports/
│   ├── models/
│   ├── paper/
│   ├── lifecycle/
│   ├── accounting/
│   └── receipts/
├── portfolio/
│   ├── positions/
│   ├── valuation/
│   ├── reconciliation/
│   └── snapshots/
├── risk/
│   ├── policies/
│   ├── limits/
│   └── preconditions/
├── research/
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
├── integrations/
│   ├── brokers/
│   ├── accounts/
│   ├── routing/
│   ├── reconciliation/
│   └── health/
├── plugins/
│   ├── india/
│   ├── global/
│   └── crypto/
├── ai/
│   ├── agents/
│   ├── models/
│   ├── features/
│   └── evaluation/
└── infrastructure/
    ├── persistence/
    ├── messaging/
    ├── observability/
    └── config/
```

## Placement rules

1. Domain objects contain business concepts and no broker SDK types.
2. Application services coordinate use cases; they do not own market-specific rules.
3. Execution models describe fills/orders; broker adapters remain under integrations/plugins.
4. Research code owns historical-data provenance and replay; it cannot silently modify source evidence.
5. India/global/crypto rules live in their plugin areas.
6. Infrastructure implements persistence, messaging, config, and observability behind ports.
7. A new module should get its own subpackage when it has independent invariants, tests, or a likely plugin boundary.
8. Do not create one giant `utils.py`, `services.py`, or `models.py` for unrelated concerns.

This is a target map, not a demand for an immediate mass file move. Existing files should be migrated incrementally as they are modified and tested.
