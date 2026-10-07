# Research Provenance and Fingerprints

## Purpose

Every research run must have a deterministic identity derived from the material inputs that can affect its result.

## Fingerprint inputs

The canonical provenance record includes:

```text
Dataset ID/version
Instrument master version
Market rule version
Execution model version
Simulation profile
Code revision
Configuration revision
Random seed (when applicable)
Additional declared inputs
Structured material run configuration (when supplied)
```

## Structured material run configuration

`ResearchRunConfiguration` is a typed, immutable value object that captures the
material configuration actually in effect for a run. It participates in
provenance identity through the existing `ResearchProvenance` payload and the
existing fingerprint; it exposes no hashing API of its own.

```text
ResearchRunSpec
      +
ResearchRunConfiguration
      ↓
ResearchProvenance
      ↓
ResearchProvenance.fingerprint()   ← the single reproducibility identity
```

Captured material inputs:

| Area | Captured |
|---|---|
| Strategy | strategy id, version, sorted parameters |
| Execution | profile name, latency, slippage bps, partial fill ratio, fee bps, effective fill-model identities/versions, volume participation rate, slippage model, charge model identity and material parameters |
| Replay/account state | `allow_incomplete`, account-state sampling policy |
| Policy | granted capabilities, live-trading flag, manual-approval flag |
| Broker constraints | name, minimum order value, minimum quantity, minimum margin amount/currency |
| Starting capital | capital source, currency, cash, available cash, blocked cash, margin used, margin available, buying power |

Strategy identity is taken from authoritative `StrategyIR` when the run uses the
runtime-neutral evaluation service. A bare callable exposes no configuration, so
identity stays absent rather than being introspected or invented.

## Canonicalization rules

1. Mapping key order does not affect the fingerprint.
2. Ordered sequences preserve their order.
3. Sets and frozensets are ordered deterministically before serialization.
4. `Decimal` values keep their exact representation, so `Decimal("1")` and
   `Decimal("1.0")` remain distinct.
5. `None` is preserved and stays distinct from zero.
6. Enums serialize through their canonical value.
7. No case folding and no whitespace normalization.
8. No aliasing or implicit defaults that merge distinct values.
9. Unsupported Python objects raise instead of silently stringifying.
10. Serialization is deterministic JSON with sorted keys, stable separators,
    and UTF-8 encoding.

## Excluded from identity

`run_id`, result UUIDs, timestamps and wall-clock time, account IDs, broker
connection IDs, artifact URIs, `source_id` used as logical dataset identity,
arbitrary object string representations, dictionary insertion order, and other
runtime-only metadata do not affect the fingerprint. `run_id` identifies a run
instance and is deliberately excluded from reproducibility identity.

## Experiment identity and run membership

An `Experiment` is a logical grouping of research execution instances. Its
identity and human-facing metadata do not declare or duplicate the strategy,
parameters, execution model, replay policy, or other material run configuration.

`ResearchRunRecord` identifies one execution instance, and `ResearchResult`
is the result bound to that run. Experiment membership stores only the
`run_id` reference.

The current semantic boundary is:

```text
Experiment
   │ 1
   ├── * ResearchRunRecord (by run_id)
   │      └── 0..1 ResearchResult
```

A run may belong to at most one experiment. An experiment may contain many runs,
including runs that intentionally vary strategy identity, parameters,
simulation models, random seeds, or other material inputs. Membership does not
copy, override, or constrain `ResearchRunConfiguration` or
`ResearchProvenance`.

The in-memory experiment manager owns only the association index and logical
experiment metadata. The durable SQLite experiment catalog now stores only
experiment metadata in `research_experiments` and explicit `experiment_id ↔ run_id`
membership in `research_experiment_runs`. The membership table enforces one
experiment per run at the database boundary, and attachment requires the
referenced `research_runs` row to exist. Existing research run/result stores remain
authoritative for run state, result payloads, configuration, and provenance.
Experiment comparison results are not persisted by this slice.

The application read side uses `ExperimentReadService` to compose the durable
experiment catalog with the existing `ResearchRunRepository`. An
`ExperimentSnapshot` contains only the logical `Experiment` and its authoritative
`ResearchRunRecord` instances. The read service rejects a catalog membership
that cannot be resolved to an existing run or whose run ownership is
inconsistent. Research results remain outside this snapshot and are rehydrated
through `ResearchRunReadService`, preserving the existing result/provenance
authority boundary.

## Fail-closed rule

When a run declares structured run configuration, the effective configuration
must match the declared one. A mismatch, or a material input that cannot be
represented canonically, fails the run instead of claiming a reproducible
identity. Provenance that supplies no structured configuration keeps its
previous canonical payload exactly.

## Rules

1. Canonical serialization must be deterministic.
2. Mapping key order must not affect the fingerprint.
3. Any material input change must change the fingerprint.
4. The fingerprint is an identity/checksum, not proof that the underlying data is truthful.
5. Source data and artifacts must remain separately retrievable.
6. An AI/LLM may explain a provenance record but cannot modify it after the run has been recorded.

## Result identity

```text
ResearchResult
      +
ResearchProvenance fingerprint
      ↓
Reproducibility identity
```

A result comparison should surface provenance differences before comparing headline metrics.
