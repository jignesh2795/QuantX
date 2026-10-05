# R1-C10 Backtest Research Provenance Binding

**Implementation status:** implementation on `feat/r1c10-backtest-provenance-binding`; external OpenCode validation is required before merge.

## Objective

Bind deterministic backtest results to the existing canonical `ResearchProvenance` / `ResearchRunSpec` identity model so a backtest result is optionally reproducibility-addressable using the repository's existing provenance/fingerprint machinery.

No second provenance system. No new hashing implementation. No conversion of `BacktestResult` into `ResearchResult`.

## Canonical provenance reuse

`ResearchProvenance` is authoritative and unchanged: required identity/version fields, optional random seed, `extra`, canonical payload, SHA-256 fingerprint, fail-closed construction. C10 attaches caller-supplied `ResearchProvenance` objects as-is and reuses `fingerprint()` / `canonical_payload()` without reimplementation.

## Optional binding

`BacktestResult.provenance` defaults to `None` and `DeterministicBacktestService.run()` accepts an optional `provenance` parameter. Existing callers remain valid without providing provenance.

## No-provenance behavior

A backtest without supplied provenance behaves exactly as before: `result.provenance is None`, no `dataset_id` / `code_revision` / fingerprint attributes appear, and no provenance is inferred from git, catalog, clock, environment, configuration, filesystem, package metadata, or broker/data-provider metadata. The existing anti-fabrication expectations remain valid.

## Dataset coherence rule

When provenance is supplied, the backtest collects the distinct `(source_id, dataset_version)` pairs across replay frames and requires:

1. exactly one distinct pair exists;
2. the observed `dataset_version` equals `provenance.dataset_version`.

Otherwise it raises `ValueError` and produces no result. It never silently chooses one dataset, silently merges heterogeneous datasets, or fabricates a dataset identity.

## Declared-version matching

The declared `provenance.dataset_version` must equal the single observed dataset version. A mismatch fails closed with no silent rebinding.

## Multi-instrument same-dataset support

Under the R1-C9 replay boundary, multiple per-instrument `HistoricalDataSeries` sharing one dataset/source identity bind to one singular `ResearchProvenance`. Instruments may differ; dataset evidence must not. The single-instrument `HistoricalDataSeries` contract is unchanged.

## Heterogeneous multi-dataset deferral

Provenance binding for replay evidence spanning more than one `(source_id, dataset_version)` pair is explicitly deferred. Such input fails closed when provenance is supplied. Heterogeneous identity is not encoded into `extra`.

## Caller-declared trust boundary

The backtest intentionally has no catalog dependency, so `dataset_id` (and other non-observable declared fields such as revisions and versions) cannot be verified against a catalog. They are caller declarations, enforced non-empty by the `ResearchProvenance` constructor, never invented by the backtest. This is an explicit trust boundary, not a reason to add catalog, git, clock, or environment coupling.

## Separation of provenance from fidelity

`BacktestFidelity` remains evidence/model quality; `ResearchProvenance` remains input/run identity. Neither depends on the other, and no provenance fields are added to `BacktestFidelity`.

## Fail-closed rules

- No supplied provenance → `None`, current behavior preserved.
- Heterogeneous observation datasets + supplied provenance → `ValueError`.
- Declared version mismatch → `ValueError`.
- Empty required provenance fields → `ResearchProvenance` construction fails before the backtest runs.
- Missing evidence is never converted into an identity.

## Compatibility

- C4 receipt-driven `account_states` unchanged.
- C7 exact-current sampling unchanged (still default).
- C8 valuation provenance unchanged.
- C9 multi-series synchronization unchanged.
- No LIVE, broker, reconciliation, recovery, risk, persistence, or pre-trade semantics changed.
- No `HistoricalReplay` / `HistoricalDataSeries` changes.

## Acceptance criteria

Focused tests must cover: default absence with no fabricated attributes; caller-supplied provenance attached unchanged (identity-preserving); identical declarations give identical fingerprints; materially changed declarations give different fingerprints; heterogeneous datasets fail closed; declared-version mismatch fails closed; shared-dataset multi-instrument binding with correct C9 sampling, C8 evidence, and C4 snapshots; existing C4/C7/C8/C9 regression preserved.

Then run full pytest, changed-file Ruff, Ruff format check, strict mypy for changed production files, and `git diff --check`.

## Deferred

C10 does not add configurable freshness thresholds, heterogeneous multi-dataset provenance composition, catalog-coupled verification, margin/buying-power evolution, financing/FX, new intrabar models, UI/API work, or AI/ML valuation.
