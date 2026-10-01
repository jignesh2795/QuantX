# Historical Data Integrity and No-Hallucination Policy

## Purpose

QuantX must never manufacture historical market data, fills, prices, fees, corporate actions, contract metadata, or performance results when the source data does not support them.

Historical simulation and research are evidence-driven. Any unavailable value must remain unavailable, be explicitly estimated by a declared model, or cause the relevant result to be marked incomplete.

## Core rule

> **Unknown is not zero, and unavailable is not invented.**

The research/backtest system must distinguish:

- observed data;
- broker/exchange-supplied data;
- derived deterministic values;
- model-estimated values;
- assumptions/configuration;
- unavailable values.

Every simulation result must preserve this provenance.

## Historical data layers

```text
Raw Source Data
      ↓
Validated / Normalized Data
      ↓
Derived Features
      ↓
Execution Simulation
      ↓
Performance Results
```

Each layer must retain a reference to the source and transformation that produced it.

## Required provenance

A historical run should record at least:

```text
DataSourceId
DatasetVersion
Instrument/Contract identity
MarketContext
Time range
Timezone
Data frequency
Completeness status
Corporate-action adjustment status
Contract-master version
Fee/charge rule version
Market-rule version
Simulation profile
Execution-model version
Model version, if any
Random seed, if stochastic
Code/configuration revision
```

## Missing-data behavior

When historical data is missing:

1. Detect the gap.
2. Record the gap explicitly.
3. Do not fabricate candles, trades, quotes, order-book states, or fills.
4. Apply a declared fallback only when the selected simulation profile permits it.
5. Mark affected results with a completeness/fidelity status.
6. Prevent a result from being presented as fully historical when material data was unavailable.

Examples:

```text
Missing bid/ask
→ do not invent a spread.
→ use a declared bar-only model or mark quote-dependent metrics unavailable.

Missing order-book depth
→ do not invent queue position.
→ use a declared liquidity approximation only if enabled.

Missing contract specification
→ do not infer lot size or multiplier from an unrelated contract.
→ block the simulation or mark the contract unsupported.
```

## No look-ahead leakage

Historical research must enforce strict temporal causality:

```text
At time T
→ only data with timestamp <= T and permitted processing latency is usable.
```

Future candles, future quotes, future corporate actions, future contract metadata, and post-period revisions must not leak into a historical decision unless the experiment explicitly models that information as historically available at the time.

## Revised and corrected source data

Historical datasets may be corrected after their original publication. QuantX should record dataset versions so that:

- a later corrected run can be reproduced;
- an earlier run is not silently rewritten;
- result comparisons can identify dataset-version differences.

## Corporate actions and contract changes

Adjusted and unadjusted series must be explicit. QuantX must not silently mix them.

For derivatives, contract specifications must be versioned by effective date. Lot size, multiplier, expiry, strike, settlement, and symbol mappings must come from the applicable contract-master version rather than inferred generically.

## Result confidence and completeness

Every historical result should expose a machine-readable fidelity/completeness classification such as:

```text
COMPLETE_OBSERVED
COMPLETE_WITH_DETERMINISTIC_DERIVATIONS
MODEL_ESTIMATED
INCOMPLETE
BLOCKED
```

A result containing material model estimates must not be described as purely observed historical performance.

## AI-assisted historical simulation

AI/ML may later estimate execution characteristics from real historical observations, for example:

```text
fill probability
slippage
market impact
latency
adverse selection
liquidity response
```

The AI model must never silently replace missing source facts. It may only provide an explicitly declared estimate through a versioned simulation model interface.

Record:

```text
model_id
model_version
training_dataset_id
feature_schema_version
inference_configuration
random_seed, when applicable
prediction timestamp / causal cutoff
```

If the model cannot produce a justified estimate, the simulator must return unavailable/blocked rather than inventing a value.

## Backtest result presentation

UI, reports, APIs, and agents must show provenance and limitations alongside headline metrics.

At minimum, a result should be able to answer:

```text
Where did this data come from?
Was it complete?
Which values were observed?
Which values were derived?
Which values were estimated?
Which execution assumptions were used?
Which dataset and contract versions were used?
Can the run be reproduced?
```

## Agent / LLM safety rule

LLMs and agents may summarize, explain, compare, or reason over recorded results, but they must not create unsupported historical facts.

If the requested conclusion cannot be established from the recorded dataset and provenance, the agent must say that the evidence is insufficient.

The result ledger, not the language model, is the source of truth for historical numbers.
