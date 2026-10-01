# Paper Execution and Research Fidelity

## Purpose

Paper trading and historical simulation must be as close to live execution as the available evidence permits, while never presenting modeled behavior as observed fact.

## Shared execution semantics

Paper execution must reuse the same:

- TradeIntent;
- allocation;
- constraint evaluation;
- pre-trade risk;
- routing decision;
- order lifecycle;
- execution context;
- position accounting;
- reconciliation semantics;

used by live execution wherever the semantics are applicable.

Only the final external venue interaction is replaced by a simulation engine.

```text
Strategy
  ↓
TradeIntent
  ↓
Allocation
  ↓
Constraints
  ↓
Risk
  ↓
Routing
  ↓
ApprovedExecutionRequest
  ├──────────────→ Live Broker
  └──────────────→ Paper Execution Engine
```

## Fidelity is evidence-dependent

The simulator must never silently create realism that the source data cannot support.

Examples:

```text
OHLCV only
→ bar-based execution model

OHLCV + bid/ask
→ spread-aware model

Trades + quotes
→ quote/trade sequencing model

Level-2/order-book data
→ depth and queue-aware model
```

The selected fidelity must be recorded in the experiment provenance.

## Execution-model components

Paper execution should be composed from replaceable components:

```text
PaperExecutionEngine
├── Price/Quote Model
├── Fill Model
├── Slippage Model
├── Latency Model
├── Liquidity Model
├── Fee/Charge Model
├── Rejection Model
└── Execution Policy
```

Each component must expose its version/configuration to the result ledger.

## Realistic behavior

Where supported by data and market rules, simulation should model:

- bid/ask spread;
- market versus limit semantics;
- stop triggering;
- partial fills;
- price improvement or adverse selection;
- latency;
- market-session restrictions;
- liquidity limitations;
- trading halts/rejections;
- fees, commissions, taxes and other charges;
- funding/borrow/carry where applicable;
- contract and lot constraints;
- exchange/broker order restrictions.

## Deterministic and stochastic modes

Every stochastic simulation must record a random seed.

A deterministic mode must be available for unit tests and reproducibility.

```text
same dataset
+ same configuration
+ same model versions
+ same seed
→ same result
```

A changed seed or model version must produce a distinct provenance identity.

## AI-assisted execution models

AI/ML may later estimate execution characteristics from real observations, including:

- fill probability;
- slippage;
- market impact;
- latency;
- adverse selection;
- liquidity response.

AI must operate behind an explicit model interface and cannot alter the core order/risk semantics.

The simulator must record:

```text
model_id
model_version
training_dataset_id
feature_schema_version
causal_cutoff
inference_configuration
```

An AI model may estimate an unavailable execution characteristic only when the experiment explicitly enables that model and provenance records the estimate.

## No fabricated historical fills

A simulated fill is never a historical fact unless an actual historical execution record exists.

Simulation results must distinguish:

```text
OBSERVED_EXECUTION
SIMULATED_EXECUTION
MODEL_ESTIMATED_EXECUTION
UNAVAILABLE
```

## Paper/live parity testing

The project should maintain contract tests that feed identical approved execution requests into paper and live adapter interfaces and verify that differences arise only from the venue interaction layer.

Examples:

- identical validation outcomes;
- identical order semantics;
- identical lifecycle transitions;
- identical account isolation;
- identical risk constraints;
- equivalent rejection categories.

## Research result labels

Every paper or historical result should carry a fidelity classification consistent with the historical-data integrity policy:

```text
COMPLETE_OBSERVED
COMPLETE_WITH_DETERMINISTIC_DERIVATIONS
MODEL_ESTIMATED
INCOMPLETE
BLOCKED
```

The UI/API must display important limitations alongside headline performance metrics.

## Promotion path

A strategy should be promotable through:

```text
BACKTEST
  ↓
REPLAY
  ↓
SHADOW
  ↓
PAPER
  ↓
LIVE APPROVAL
  ↓
LIVE
```

Promotion must not silently change strategy, parameters, risk policy, routing policy, market rules, contract metadata, or execution model.

## Core invariant

> Paper trading is a simulation of the same trading system, not a separate shortcut system.
