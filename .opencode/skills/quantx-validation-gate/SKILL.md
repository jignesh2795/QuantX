---
name: quantx-validation-gate
description: Generates exact read-only validation prompts and evidence requirements for QuantX — focused/full pytest, changed-file Ruff, strict mypy, git diff --check, scope and integrity audits. Use when validation evidence is requested. Never fixes during validation.
metadata:
  quantx/role: validation
---

# QuantX Validation Gate

This skill does not implement fixes. It generates (or executes) a read-only validation request and returns evidence.

## Required behavior

Given a branch/HEAD and task scope, the validation prompt must:

- use a detached temporary worktree; never modify the primary checkout;
- state exact HEAD and base;
- run focused tests for the touched area;
- run the full suite;
- run changed-file Ruff;
- run strict mypy on changed production files;
- run `git diff --check`;
- audit semantic invariants and safety boundaries;
- check exact changed-file scope against the stated task;
- verify the primary checkout remains clean;
- prohibit reset, revert, rebase, amend, clean, fixes, commits, pushes, and merges.

## Exact commands

```powershell
uv run pytest tests/unit/<focus> -q          # focused
uv run pytest -q                              # full suite
uv run ruff check <changed .py files>         # changed-file lint
uv run ruff format --check <changed files>    # format check
uv run mypy                                   # strict typecheck (package quantx)
git diff --check                              # whitespace errors
git status --porcelain                        # integrity
```

Repository gate: **pytest green + changed-file Ruff clean + `git diff --check` clean.**

Notes:

- Repo-wide Ruff has pre-existing findings; the gate is changed-file Ruff only.
- Optional Dhan tests need `uv sync --dev --extra dhan`; otherwise they self-skip.
- Test-count baseline to compare against lives in `docs/STATUS.md`.

## Evidence discipline

Require exact command/result summaries with counts. Never accept "tests pass" without command/count evidence.

## Verdicts

- **PASS** — all mandatory gates green and no blocking semantic finding.
- **BLOCKED** — any mandatory gate red or any unresolved safety/semantic blocker.

After evidence is returned, the deciding agent — not the validation run — determines whether to fix or merge.
