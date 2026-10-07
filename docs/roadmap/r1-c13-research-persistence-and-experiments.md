# R1-C13 Research Persistence, Orchestration, and Experiments

**Status:** Complete through C13.8.

## Purpose

R1-C13 established the durable research lifecycle needed to persist, rehydrate, compare, and manage research runs and experiments without introducing a competing provenance identity system.

## Completed slices

- **C13.3** — durable SQLite research persistence
- **C13.4-A** — research-run orchestration
- **C13.4-B** — backtest lifecycle binding
- **C13.4-C** — lifecycle hardening
- **C13.5** — research-run rehydration
- **C13.6-A..F** — experiment comparison, association, metadata ownership, persistence, read rehydration, and comparison read
- **C13.7** — experiment detail read
- **C13.8** — experiment write boundary

## C13.8 boundary

`ExperimentWriteService` is a thin application boundary:

```text
Application
    ↓
ExperimentWriteService
    ↓
ExperimentRepository
    ↓
durable persistence
```

It delegates experiment creation and run attachment without duplicating repository validation or persistence semantics.

## Architectural result

The research plane now has durable lifecycle boundaries:

```text
ResearchRun
    ↓
durable lifecycle
    ↓
ResearchResult / provenance
    ↓
Experiment
    ├── association
    ├── comparison
    ├── detail read
    └── write boundary
```

C13 does not own market-data ingestion. Dataset ingestion remains a separate data-plane concern and is the subject of R1-C14.

## Completion rule

C13 is considered complete at merged main state. Any C13 implementation branches that contain no unique work relative to current main are historical/superseded and are not current implementation branches.
