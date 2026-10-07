# R1-C14 Deterministic Historical Dataset Ingestion & Provenance Composition

**Status:** Planning.

**Baseline:** `main @ bb3e710eaaefbe70f8a4c5026ad07a3ab0f1aa84`

## Objective

Establish a deterministic, provider-neutral historical dataset ingestion application boundary that composes existing QuantX data-plane and research-plane seams.

C14 is a composition milestone, not a greenfield ingestion/storage project.

## Existing canonical capabilities

QuantX already provides:

- vendor-neutral `MarketDataPort`
- canonical `Candle` observations
- SQLite-backed `MarketDataStore`
- `DatasetIdentity` / `DatasetVersion`
- `DatasetCatalog`
- historical-data quality/completeness assessment
- dataset-backed research access
- lossless historical observations
- `ResearchProvenance`
- durable `ResearchRun` lifecycle
- durable `Experiment` lifecycle

## Target composition

```text
Pre-registered DatasetVersion
        ↓
Provider / MarketDataPort
        ↓
C14 ingestion application boundary
        ↓
canonical candles
        ↓
quality evidence
        ↓
MarketDataStore
        ↓
dataset-backed read
        ↓
ResearchProvenance
        ↓
ResearchRun
```

## Boundary ownership

| Concern | Canonical owner |
|---|---|
| Provider-specific retrieval | Provider adapter |
| Provider-neutral retrieval | `MarketDataPort` |
| Ingestion orchestration | C14 application boundary |
| Dataset identity | `DatasetVersion` / `DatasetCatalog` |
| Quality assessment | Historical-data quality seam |
| Observation persistence | `MarketDataStore` |
| Dataset-scoped research read | Dataset access seam |
| Reproducibility identity | `ResearchProvenance.fingerprint()` |
| Research lifecycle | C13 ResearchRun services |
| Experiment lifecycle | C13 Experiment services |

## Identity rule

Dataset identity is pre-declared and authoritative.

C14 should use:

```text
register DatasetVersion
        ↓
ingest against that identity
        ↓
persist observations with that identity
```

C14 should not silently create or infer dataset identity from provider/source information.

## Core invariants

1. Dataset identity is always explicit.
2. Dataset catalog remains authoritative for registered dataset versions.
3. Identity conflicts fail closed.
4. Canonical candles remain lossless.
5. No observations are fabricated.
6. Completeness is never inferred without explicit evidence.
7. Existing MarketDataStore duplicate/conflict semantics remain authoritative.
8. C14 remains provider-neutral.
9. Provenance is never fabricated.
10. Existing research provenance remains the single reproducibility identity.

## Proposed slices

- C14.1 — roadmap/state reconciliation
- C14.2 — ingestion contract and application boundary
- C14.3 — provider/MarketDataPort composition
- C14.4 — dataset identity/version binding
- C14.5 — quality/evidence binding
- C14.6 — durable persistence composition
- C14.7 — Dhan vertical composition
- C14.8 — research provenance binding
- C14.9 — end-to-end deterministic proof

## Salvage sources

### `feat/m2-dataset-ingestion-workflow-v1`

Contains unique historical dataset-ingestion composition and Dhan-to-SQLite tests. Treat as source material; do not merge wholesale.

### `feat/dhan-host-market-data-wiring-v1`

Contains unique Dhan host market-data composition and tests. Treat as source material; do not merge wholesale.

## Explicit non-goals

C14 does not introduce:

- scheduling
- generic job orchestration
- streaming market data
- distributed ingestion
- cloud object storage
- generic ETL
- automatic source-content verification
- production historical-data service
- UI
- AI/ML
- optimization
- broad broker expansion

## Completion proof

C14 must demonstrate that the same declared dataset identity can be followed deterministically from provider retrieval through canonical persistence and dataset-scoped read, and that the resulting identity can bind into the existing research provenance/run lifecycle without duplicate architecture.
