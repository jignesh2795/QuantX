# QuantX Current Package Map

This document separates the **implemented package map** from the **long-term target map**. New functionality should be placed in the smallest coherent package rather than accumulating in catch-all files.

## Implemented top-level areas

Current implementation areas include:

```text
src/quantx/
├── domain/
├── application/
├── execution/
├── integrations/
├── research/
├── persistence/
├── india/
├── plugins/
├── ports/
└── strategy/
```

These are current implementation areas; this is not a claim that every long-term package boundary has already been materialized.

### Current execution/recovery boundaries

```text
execution/
├── idempotency/
├── preconditions/
├── receipts/
├── transactions/
├── continuation.py
├── lifecycle.py
├── dispatch.py
├── paper.py
├── paper_session.py
└── order_lifecycle.py

application/
├── reconciliation.py
├── evidence_refresh.py
└── uncertain_submission.py
```

The exact tree may evolve incrementally. Ownership of invariants matters more than directory symmetry.

### Current LIVE startup/control boundaries

`application/runtime.py` owns the one-shot recovery-backed application startup lifecycle; `application/production.py` composes the durable process runtime; `application/execution.py` is the application-owned LIVE submission boundary and now requires a started `ApplicationRuntime` plus final trading-gate authorization before broker submission. `execution/trading_gate.py` owns gate state and submission authorization, while `persistence/sqlite/trading_gate.py` supplies durable gate synchronization.

### Lifecycle distinction

There are two deliberately different lifecycle concepts:

- `execution/order_lifecycle.py` is a small event/state-transition model for explicit lifecycle events, including uncertain `UNKNOWN` outcomes.
- `execution/receipts/lifecycle.py` is the authoritative order-level aggregate reconstructed from immutable execution receipts and is the source used for continuation/recovery decisions.

They should not be merged merely because both contain the word `lifecycle`; they operate at different abstraction boundaries.

## Long-term target organization

The broader modular target remains useful, but it is not an instruction to perform a mass migration now:

```text
src/quantx/
├── domain/
├── application/
├── execution/
├── portfolio/
├── risk/
├── research/
├── integrations/
├── plugins/
├── ai/
└── infrastructure/
```

Subpackages should be introduced when a responsibility has an independent invariant, test surface, or stable integration/plugin boundary.

## Placement rules

1. Domain objects contain business concepts and no broker SDK types.
2. Application services coordinate use cases; they do not own market-specific rules.
3. Execution owns normalized execution semantics and safety boundaries.
4. Broker adapters remain under integrations/plugins and must not leak vendor SDK types into the core.
5. Research owns historical-data provenance and replay; it cannot silently modify source evidence.
6. India/global/crypto rules live behind their respective market/plugin boundaries as those implementations mature.
7. Infrastructure implements persistence, messaging, config, and observability behind stable boundaries.
8. A new module should get its own subpackage when it has independent invariants, tests, or a likely plugin boundary.
9. Do not create one giant `utils.py`, `services.py`, or `models.py` for unrelated concerns.

## Migration rule

When an existing module is modified, move it only when the new boundary is justified by ownership and callers can be migrated safely. Avoid repository-wide structural migrations while execution-integrity work is active.