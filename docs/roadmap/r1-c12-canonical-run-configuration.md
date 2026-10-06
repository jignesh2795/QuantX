# R1-C12 Canonical Research Run Configuration

**Implementation status:** implementation on `feat/r1c12-canonical-run-configuration`; external OpenCode validation is required before merge.

## Problem

C11 bound dataset identity correctly: observations carry logical `dataset_id`
plus `dataset_version`, and provenance must match both. However, most other
material inputs to a backtest remained declared-only. Two runs could differ in
latency, slippage, fees, partial-fill ratio, volume participation, sampling
policy, broker constraints, or starting capital and still share one
`ResearchProvenance.fingerprint()`.

The sharpest example is execution identity: provenance could declare
`execution_model_version="paper-core-v0.3"` while the run actually filled with
`BASIC_BAR/basic-bar-v4`. The declared configuration did not describe the
effective one.

## Motivation

Every material input that can change a result must either change the canonical
reproducibility identity or cause the run to fail closed. C12 makes the
effective configuration participate in the single existing fingerprint rather
than introducing a second identity system.

## Relationship

```text
ResearchRunSpec
      +
ResearchRunConfiguration
      ↓
ResearchProvenance
      ↓
ResearchProvenance.fingerprint()   ← the only reproducibility identity
```

`ResearchRunConfiguration` is a typed immutable value object with a canonical
payload. It deliberately exposes no fingerprint or hash API.

## Canonical field inventory

| Area | Fields |
|---|---|
| Strategy | strategy id, version, sorted parameters |
| Execution | simulation profile name, `latency_ms`, `slippage_bps`, `partial_fill_ratio`, `fee_bps`, effective fill-model identities and versions, volume participation rate, slippage model identity and parameters, charge model identity and material parameters |
| Replay/account state | `allow_incomplete`, account-state sampling policy |
| Policy | granted capabilities, live-trading flag, manual-approval flag |
| Broker constraints | name, minimum order value, minimum quantity, minimum margin amount and currency |
| Starting capital | capital source, currency, cash balance, available cash, blocked cash, margin used, margin available, buying power |

`execution_models` is a sorted tuple of model identities because one run may use
both the quote route and the candle route; a single ID/version pair could not
describe that faithfully.

## Included and excluded inputs

Included: only material inputs the backtest boundary actually knows. An opaque
custom charge model has no canonical material parameters, so it is recorded as
absent rather than stringified, and a declared configuration that expects one
fails closed.

Excluded from identity: `run_id`, result UUIDs, timestamps, wall-clock time,
account IDs, broker connection IDs, artifact URIs, `source_id` used as logical
dataset identity, arbitrary object string representations, dictionary insertion
order, and runtime-only metadata.

`run_id` remains part of `ResearchRunSpec` but no longer affects the
fingerprint: two runs of one configuration are the same experiment.

## Strategy identity

When the run uses `StrategyEvaluationService`, strategy identity and parameters
come from the authoritative `StrategyIR`. A bare callable exposes no
configuration, so identity stays absent and a declared strategy identity fails
closed. Arbitrary callables are never introspected.

## Backtest integration

`DeterministicBacktestService` derives the effective configuration from the run
it actually performs and, when the supplied provenance declares structured run
configuration, requires the declared configuration to match the effective one.
A mismatch raises before strategy execution, fills, accounting, or account-state
evolution. Provenance is still attached unchanged by identity.

## Canonicalization rules

1. Mapping key order does not affect the fingerprint.
2. Ordered sequences preserve order.
3. Sets and frozensets are ordered deterministically.
4. `Decimal` keeps its exact representation; `Decimal("1")` and `Decimal("1.0")` stay distinct.
5. `None` is preserved and stays distinct from zero.
6. Enums use canonical values.
7. No case folding; no whitespace normalization.
8. No aliasing or implicit defaults that merge distinct values.
9. Unsupported Python objects raise instead of silently stringifying.
10. Deterministic JSON: sorted keys, stable separators, UTF-8.

## Backwards compatibility

Provenance that supplies no structured run configuration keeps its previous
canonical payload exactly, so existing fingerprints are unchanged. Supplying
structured configuration opts the caller into fail-closed verification.
`random_seed` remains the final element of `reproducibility_key` for
compatibility.

`ExperimentManager.compare()` now uses canonical strategy identity from
structured configuration instead of inferring a family from `run_id`. When
strategy identity is unavailable it does not invent equivalence and reports the
difference.

## Explicit non-goals

No new hashing algorithm, no second provenance subsystem, no catalog or
source-content verification, no broker or LIVE behavior change, no accounting
redesign, no margin evolution, no FX/tax, no UI/API, no AI/ML work, and no
unstructured free-form configuration dumping into `extra`.

## Validation evidence expected

Focused C12 tests must cover fingerprint equality under reordering, inequality
for every material input, exact `Decimal` semantics, explicit exclusions,
fail-closed behavior for undeclared or unrepresentable configuration, and C11
regression. Then full pytest, changed-file Ruff, Ruff format check, strict
mypy, and `git diff --check`.