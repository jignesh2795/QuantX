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

## Git worktree lifecycle (mandatory)

- Treat every temporary validation or task worktree as a resource with an explicit purpose, path, base/head SHA, owner, and cleanup condition. Inspect `git worktree list --porcelain` before creating worktrees; reuse a suitable task worktree across reruns instead of creating another checkout for every command.
- A VALIDATION ONLY run must use a detached worktree at the exact requested SHA. Capture the final SHA, command results, and any evidence needed for the report before removing that temporary worktree.
- At task completion, remove only worktrees created for that task when no further validation or edits depend on them. Prefer `git worktree remove <path>`; a pushed branch and its commits remain available after its working directory is removed. Recreate the worktree from the branch if follow-up changes are required.
- Before removal, inspect `git status --short` and preserve any required logs/evidence. Use `git worktree remove --force <path>` only after verifying that the path is a disposable worktree created by the current task and that no needed or user-owned changes will be lost.
- Never remove the primary checkout or another active task's worktree. Do not delete branches or commits as part of worktree cleanup. Do not broadly delete `Temp\opencode`, temporary folders, or other paths as a substitute for Git worktree-aware cleanup.
- After cleanup, verify with `git worktree list --porcelain` that the task-created temporary worktree is gone. `git worktree prune` is for stale administrative records whose worktree directories are already absent; it does not replace removing a live worktree. Inspect `git worktree prune --dry-run` before pruning.
- If a worktree must remain for an explicit follow-up, report it as ACTIVE with its path, purpose, branch/SHA, and cleanup owner/condition. Do not silently leave a completed task's temporary worktree behind. If safe cleanup is blocked, report the exact path and reason instead of forcing removal.
