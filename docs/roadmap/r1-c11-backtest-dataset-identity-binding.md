# R1-C11 Backtest Dataset Identity Binding

**Implementation status:** implementation on `feat/r1c11-backtest-dataset-identity`; external OpenCode validation is required before merge.

## Objective

Close the remaining C10 provenance-integrity gap: C10 validates the dataset version but does not validate that the replay's `source_id` corresponds to the supplied `ResearchProvenance.dataset_id`. C11 binds both identity dimensions without adding catalog, filesystem, or inference dependencies to the backtest.

## Canonical invariant

When provenance is supplied, the replay must contain exactly one `(source_id, dataset_version)` pair, and it must equal `(provenance.dataset_id, provenance.dataset_version)`:

| Replay evidence | Result |
|---|---|
| One source + one version, both match provenance | ✅ bound |
| Same source + different version | ❌ `ValueError` |
| Different source + same version | ❌ `ValueError` |
| Different source + different version | ❌ `ValueError` |
| Multiple instruments from same dataset | ✅ bound |
| Multiple instruments from different datasets | ❌ `ValueError` |
| No provenance supplied | Existing C10 behavior; `result.provenance is None` |

No normalization, aliasing, inference, or catalog lookup. Mismatch means rejection.

## Trust boundary preserved

Dataset/catalog resolution stays outside the backtest: dataset access produces historical observations, the backtest validates the identity relationship those observations carry against the caller's canonical declaration. The backtest gains no catalog, store, filesystem, network, broker, git, clock, or environment dependency. `dataset_id` remains caller-declared; the backtest enforces equality, not authority.

## Separation preserved

- `ResearchProvenance` schema, fingerprint algorithm, and fail-closed construction unchanged.
- `BacktestFidelity` remains evidence/model quality with no provenance fields.
- C4 receipt-driven snapshots, C7 sampling default, C8 valuation provenance, C9 synchronization, risk/policy, execution, reconciliation, recovery, LIVE, broker, and persistence semantics unchanged.
- `HistoricalObservation`, `HistoricalDataSeries`, and `HistoricalReplay` unchanged.

## Fail-closed rules

- No supplied provenance → `None`, current behavior preserved; no mandatory provenance introduced.
- Heterogeneous observation datasets + supplied provenance → `ValueError` before strategy execution, engine setup, fills, accounting, or account-state evolution.
- Declared `dataset_id` or `dataset_version` mismatch → `ValueError`; no silent rebinding, no "closest" matching.
- Missing identity evidence is never converted into an identity.

## Compatibility

Shared multi-instrument datasets (one dataset, many instruments) continue to bind to one singular `ResearchProvenance`. Heterogeneous multi-dataset binding remains explicitly deferred, as in C10.

## Acceptance criteria

Focused tests must cover: matching source + version binds; wrong source with matching version fails; matching source with wrong version fails; multiple sources with matching version fail; same source with multiple versions fails; shared source/version across multiple instruments binds; mismatch appearing only in a later frame fails; no-provenance behavior unchanged; no catalog/store invocation possible by construction.

Then run full pytest, changed-file Ruff, Ruff format check, strict mypy for changed production files, and `git diff --check`.

## Deferred

C11 does not add heterogeneous multi-dataset provenance composition, catalog-coupled verification, source-content verification, run-configuration identity (sampling policy, simulation controls — the likely R1-C12 candidate), margin/buying-power evolution, financing/FX/tax, new fill models, UI/API, or AI/ML work.
