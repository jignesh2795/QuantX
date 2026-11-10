# QuantX Documentation

**New here?** Start with [Getting Started](GETTING_STARTED.md), then use the guides below.

## Current project state

- [STATUS.md](STATUS.md) — concise current implementation, workstreams, and safety disposition.
- [STATUS_HISTORY.md](STATUS_HISTORY.md) — preserved historical status ledger and exact-SHA validation records.

## Architecture

The numbered architecture records are grouped by topic and numeric range. The current repository contains **50 numbered top-level records** (10 core, 14 domain/execution, 26 advanced); gaps and the two distinct `40-` filenames are intentional historical numbering. The `adr/` directory and `control-and-safety-path.md` are indexed separately.

- [Core architecture (00-09)](architecture/README.md#core-00-09)
- [Domain and execution (10-29)](architecture/README.md#domain-and-execution-10-29)
- [Advanced architecture (30-56)](architecture/README.md#advanced-30-56)
- [Full architecture index and reading order](architecture/README.md)
- [Current package map](architecture/41-current-package-map.md)
- [Global market separation](architecture/32-global-market-separation.md)
- [Control and safety path](architecture/control-and-safety-path.md)
- [Architecture decisions (ADRs)](architecture/adr/)

## Implementation

See [implementation/README.md](implementation/README.md) for build sequencing, canonical contracts, exact-SHA validation, and implementation discipline.

## Roadmap

See [roadmap/README.md](roadmap/README.md) for current programme priorities, milestones, and deferred capabilities.

## Decisions

See [decisions/README.md](decisions/README.md) for durable architecture and product decisions.

## Research

See [research/README.md](research/README.md) for pinned-source comparisons and technology evaluation.

## Examples and contributing

- [Runnable local examples](../examples/README.md)
- [Contribution workflow](../CONTRIBUTING.md)
- [Contributor Code of Conduct](../CODE_OF_CONDUCT.md)
- [Security policy](../SECURITY.md)

## Documentation rules

- Maintain one canonical source for each decision or status record.
- Architecture decisions belong in `architecture/` or `architecture/adr/`.
- Implementation sequencing belongs in `implementation/`.
- Future work belongs in `roadmap/`.
- Historical status remains in `STATUS_HISTORY.md`; do not treat it as current policy.
- Temporary execution notes do not belong in the permanent architecture set.

Research → Compare → Decide → Document → Build.
