# R1-C11 Backtest Dataset Identity Evidence Binding

**Implementation status:** implementation on `feat/r1c11-dataset-identity-evidence`; external OpenCode validation is required before merge.

## Objective

Close the C10 provenance-integrity gap: C10 validated version-level coherence but never validated that replay evidence belongs to the declared logical dataset. C11 binds the complete dataset identity carried by replay observations to the supplied canonical provenance, without giving the backtest any catalog, filesystem, or inference dependency.

## Corrected architecture

QuantX distinguishes two identities that C10 incorrectly conflated:

- `dataset_id` = logical dataset identity (e.g. `"nse-eq"`);
- `source_id` = source/provider identity (e.g. `"dhan"`).

One logical dataset may arrive through different provider sources. Therefore `observation.source_id` is never compared against `provenance.dataset_id`.

Target contract:

```text
HistoricalObservation
├── snapshot
├── dataset_id
├── source_id
├── dataset_version
└── sequence
```

`dataset_id` is optional evidence (`None` = identity not carried). The dataset access/catalog boundary propagates the resolved logical `dataset_id` into observations; the backtest only validates identity evidence already present and fails closed when it is absent or mismatched.

## Canonical invariant

When `ResearchProvenance` is supplied, every replay observation must carry:

```text
observation.dataset_id == provenance.dataset_id
observation.dataset_version == provenance.dataset_version
```

The replay must contain exactly one logical `(dataset_id, dataset_version)` pair matching the supplied provenance:

| Replay evidence | Provenance | Result |
|---|---|---|
| dataset A / source X / v1 | A / v1 | bound |
| dataset A / source Y / v1 | A / v1 | bound |
| dataset B / source X / v1 | A / v1 | rejected |
| dataset A / source X / v2 | A / v1 | rejected |
| A/v1 followed later by B/v1 | A / v1 | rejected |
| A/v1 source X followed by A/v1 source Y | A / v1 | bound |
| no provenance | none | existing behavior unchanged |

No normalization: `"A"` vs `"a"` and `"A"` vs `"A "` both fail. Mismatch means rejection, before strategy execution, engine setup, fills, accounting, or account-state effects.

## Trust boundary preserved

Dataset/catalog resolution stays outside the backtest: dataset access produces observations carrying logical identity, the backtest validates it. No catalog lookup, filesystem/network access, source verification, aliasing, "closest" matching, or inferred dataset IDs.

## Separation preserved

- `ResearchProvenance` schema, fingerprint algorithm, and fail-closed construction unchanged.
- `BacktestFidelity` remains evidence/model quality with no provenance fields.
- C4 receipt-driven snapshots, C7 sampling default, C8 valuation provenance, C9 synchronization, risk/policy, execution, reconciliation, recovery, LIVE, broker, and persistence semantics unchanged.
- `HistoricalReplay` ordering and quality semantics unchanged; `HistoricalDataSeries` remains single-instrument.

## Fail-closed rules

- No supplied provenance → `None`, current behavior preserved; no mandatory provenance introduced.
- Observations without carried `dataset_id` cannot bind when provenance is supplied.
- Heterogeneous logical datasets + supplied provenance → `ValueError`.
- Declared `dataset_id` or `dataset_version` mismatch → `ValueError`; no silent rebinding.
- Missing identity evidence is never converted into an identity.

## Compatibility

Shared multi-instrument datasets (one logical dataset across instruments and sources) bind to one singular `ResearchProvenance`. Heterogeneous multi-dataset binding remains explicitly deferred, as in C10.

## Acceptance criteria

Focused tests must cover: same dataset/version across sources binds; wrong dataset with matching source/version fails; matching dataset with wrong version fails; heterogeneous logical datasets fail; later-frame logical mismatch fails; shared multi-instrument dataset binds with correct C9 sampling, C8 evidence, and C4 snapshots; whitespace/case variants fail; no-provenance behavior unchanged; rejection precedes simulation effects; supplied object attached unchanged; fingerprint behavior unchanged; C9/C10 regression preserved.

Then run full pytest, changed-file Ruff, Ruff format check, strict mypy for changed production files, and `git diff --check`.

## Deferred

C11 does not add heterogeneous multi-dataset provenance composition, catalog-coupled verification, source-content verification, run-configuration identity (sampling policy, simulation controls — the likely R1-C12 candidate), margin/buying-power evolution, financing/FX/tax, new fill models, UI/API, or AI/ML work.
