# QuantX Documentation Branching Strategy

Architecture and roadmap documentation is developed separately from production implementation.

## Branches

- `main` — stable repository baseline
- `docs/architecture-roadmap` — architecture, ADRs and roadmap work
- `feat/*` — implementation features created after architecture decisions exist
- `fix/*` — focused fixes

## Rule

Major implementation should not begin directly on `main`. A feature branch should reference the relevant architecture decision or roadmap item.

## Review path

```text
Research
  ↓
Architecture decision
  ↓
Documentation branch
  ↓
PR / review
  ↓
Merge to main
  ↓
Implementation branch
  ↓
Tests / CI
  ↓
PR / review
  ↓
Merge
```
