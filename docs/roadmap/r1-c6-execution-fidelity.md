# R1-C6 Execution Price and Fill Fidelity

## Status

**Implemented and merged in PR #65.** Final validated head: `5a58318c3978b3a78da32847d717e8bc842a8ac8`. Squash merge commit: `8067e5f3b81344698b818d950373bbcc477c170a`. External revalidation reported 1168 passed, 0 failed, 1 skipped (optional Dhan SDK test), with changed-file Ruff, strict mypy, and `git diff --check` passing.

## Repository audit and implementation direction

A repository audit after establishing this plan found that substantial execution-fidelity functionality already exists from earlier paper-execution work. The canonical current path is:

```text
PaperExecutionEngine
  -> execution.models.FillModel
  -> Fill
  -> ExecutionReceipt
  -> existing accounting
```

The canonical models already include quote-aware fills, deterministic candle fills, data-adaptive routing, slippage, latency, partial-fill ratios, and authoritative continuation/lifecycle handling. R1-C6 therefore must **not** create a second execution-model stack.

The implementation focus is hardening and converging this existing path:

- make fill proposals carry explicit reference-versus-realized execution evidence;
- enforce strong Decimal/positive-value/model identity invariants at the proposal boundary;
- preserve deterministic provenance for the realized fill;
- strengthen receipt evidence without creating a second accounting path;
- keep existing continuation/remainder semantics authoritative;
- identify the older `execution/paper/*` stack as legacy duplicate implementation rather than extending it.

The older `execution/paper/*` package is intentionally not expanded by C6. Its eventual compatibility/consolidation treatment is a separate cleanup decision so C6 does not create more duplicate abstractions.

**Planning baseline accepted after R1-C5 merge.**

R1-C5 established the deterministic transaction-cost contract:

- structured charge components;
- aggregate `ExecutionReceipt.fee` compatibility;
- deterministic generic bps charge modeling;
- model ID/version/provenance;
- preservation of the existing C4 cash/P&L accounting path.

R1-C6 extends that foundation to the execution-realization side: how an intended order becomes deterministic fills.

## Goal

Define a vendor-neutral, deterministic execution model for paper/research simulation without changing LIVE execution semantics.

The intended flow is:

```text
order intent
    ↓
execution assumptions
    ↓
fill realization
    ↓
charges (R1-C5)
    ↓
execution receipt
    ↓
existing cash/accounting/P&L
```

## Scope

### 1. Execution model contract

Define a deterministic execution-model boundary that can express:

- reference/market price;
- requested quantity;
- realized quantity;
- realized execution price;
- execution-model identity;
- model version;
- provenance/evidence.

Financial quantities and prices remain Decimal-only.

### 2. Deterministic price realization

Provide an explicit baseline model for paper/research execution.

The first model may use a simple deterministic spread/slippage assumption, but its basis must be explicit and configurable. It must not imply actual broker, exchange, or Indian-market behavior.

Identical inputs and configuration must produce identical fills.

### 3. Partial-fill semantics

Represent partial execution explicitly:

`requested quantity → fill_1 + fill_2 + ... + remainder`

Required invariants:

- realized quantity must never exceed requested quantity;
- every fill has explicit quantity and price;
- remaining quantity is deterministic;
- continuation/remainder semantics reuse the existing execution lifecycle/continuation boundaries rather than creating a parallel mechanism.

### 4. Receipt evidence

Extend the receipt boundary only where required to preserve authoritative execution evidence.

The receipt must distinguish intended/requested values from realized execution values and retain execution-model provenance.

R1-C5 structured charges remain independent and authoritative for transaction cost.

### 5. Account/P&L integration

Use the realized fills as inputs to the existing C4 path:

```text
realized fills
    ↓
FillAccounting
    ↓
CashLedger
    ↓
HistoricalAccountState
    ↓
P&L
```

Do not introduce a second accounting or P&L engine.

## Safety boundary

R1-C6 is **paper/research modeling only**.

It must not change:

- LIVE trading-gate semantics;
- broker submission;
- reconciliation;
- UNKNOWN handling;
- retry/resubmission behavior;
- recovery dispatch;
- broker SDK placement;
- account/connection safety controls.

A simulated fill is evidence of the simulation model, not evidence of a broker event.

## Explicit non-goals

Defer the following:

- current India broker tariff schedules;
- STT/GST/stamp/exchange/SEBI/DP rules;
- financing/funding/borrow costs;
- exchange or broker-specific microstructure;
- order-book queue position;
- market impact;
- network/exchange latency;
- sophisticated liquidity/volume participation models;
- multi-currency settlement.

These are later slices requiring their own contracts and evidence.

## Acceptance criteria

### Determinism
Identical order inputs, market inputs, and model configuration produce identical fills.

### Numeric integrity
No float-based financial or quantity calculations.

### Quantity integrity
Total realized quantity never exceeds requested quantity.

### Price integrity
Every realized fill has an explicit price and quantity.

### Partial-fill integrity
Remainder is explicit and compatible with the existing lifecycle/continuation model.

### Provenance
Execution-model ID, version, and provenance are retained.

### Receipt integrity
Realized execution evidence is represented without conflating it with intended order values.

### Charge integration
R1-C5 structured charges continue to flow through the existing aggregate fee/accounting path.

### Accounting integrity
Realized fills feed C4 accounting without introducing duplicate P&L logic.

### Safety
No LIVE, reconciliation, retry, UNKNOWN, or broker-boundary changes.

### Validation
Focused execution/fill/receipt/accounting tests, full test suite, changed-file Ruff, strict mypy for changed production files, and `git diff --check` must all pass.

## Design constraint

Do not solve future realism problems prematurely.

R1-C6 should establish the smallest stable execution-realization contract that later slices can extend for latency, liquidity, partial-fill realism, market impact, and venue-specific behavior without breaking the receipt or accounting boundaries.

## Deferred C5 observations

These remain backlog items and do not block R1-C6:

- positional-field-order compatibility hardening in `ExecutionReceipt`;
- unused `ChargeBreakdown.zero()` cleanup;
- broader currency-aware charge-model semantics.
