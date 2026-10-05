# QuantX OpenCode Project Instructions

Skills live in `.opencode/skills/`. This file defines **how OpenCode must behave in this repository**; skills define **what capability to load for a task**.

## Mandatory baseline

Load `quantx-core-governance` first for all QuantX work, then the smallest relevant specialist skill.

## Ownership

The coding agent owns engineering decisions, implementation, fixes, documentation, branch/PR work, and merge decisions. The owner supplies validation evidence only — do not ask the owner to design the solution unless a genuine owner-only decision is required.

```
DECISION               → AGENT
IMPLEMENTATION         → AGENT
REVIEW                 → AGENT + validation evidence
VALIDATION             → read-only validation run
MERGE/RELEASE DECISION → AGENT
```

When a task is explicitly VALIDATION ONLY: do not edit the repository. Use a detached temporary worktree, validate the exact requested HEAD, and return evidence only.

## Skill hierarchy

```
CORE       quantx-core-governance, quantx-operating-model
UNDERSTAND quantx-repo-auditor, quantx-architecture, quantx-migration-consolidation
PLAN       quantx-roadmap-planner
DOMAIN     quantx-execution, quantx-india-market, quantx-strategy-plugins,
           quantx-research-data, quantx-simulation-accounting
QUALITY    quantx-testing, quantx-adversarial-review, quantx-validation-gate
SHIP       quantx-release-gate, quantx-docs-maintainer
WORKFLOW   quantx-dev-workflow
```

Normal engineering task order: `core → audit → plan → implement → adversarial-review → validation-gate → release-gate → docs sync`.

## Repo-specific safety

- Core stays free of broker SDKs, credentials, and web frameworks; `dhanhq` imports only in `src/quantx/plugins/dhan/transport.py`.
- Decimal-only financial calculations; never float money.
- Fail closed; `UNKNOWN` is never PASS; unknown is not zero.
- No fabricated market/broker evidence; missing evidence stays UNKNOWN.
- Recovery never submits broker orders; no real broker orders in development or validation.
- Tests mirror the source tree under `tests/unit/`; no `conftest.py` conventions — use `_`-prefixed factory helpers.

## Validation response

Never say tests pass without exact command/results. When validation is requested, report exact counts, tooling results, semantic findings, scope, and repository integrity. Gate: `pytest green + changed-file Ruff clean + git diff --check clean`.
