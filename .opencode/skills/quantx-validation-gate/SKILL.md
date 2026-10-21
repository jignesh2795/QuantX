---
name: quantx-validation-gate
description: Use when validation evidence is requested — exact read-only validation prompts and requirements for QuantX: focused/full pytest, changed-file Ruff, strict mypy, git diff --check, scope and integrity audits. Never fixes during validation.
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
uv run pytest tests/unit/<focus> -q          # focused (diagnostic only)
uv run pytest -q                              # full suite
uv run ruff check <changed .py files>         # changed-file lint
uv run ruff format --check <changed files>    # format check
uv run mypy                                   # strict typecheck (package quantx)
git diff --check                              # whitespace errors
git status --porcelain                        # integrity
```

A focused/targeted pytest run is a diagnostic. It may be executed and
reported independently, but its evidence can never satisfy the release
gate's mandatory full-suite contract (see `quantx-release-gate`).

Repository gate: **pytest green + changed-file Ruff clean + `git diff --check` clean.**

Notes:

- Repo-wide Ruff has pre-existing findings; the gate is changed-file Ruff only.
- Optional Dhan tests need `uv sync --dev --extra dhan`; otherwise they self-skip.
- Test-count baseline to compare against lives in `docs/STATUS.md`.

## Executable gate

`scripts/run_validation.py` runs the gate read-only and emits machine-readable evidence:

```powershell
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --expected-head <sha>
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --skip-full   # degrades to UNKNOWN, never PASS
```

- Runs: full `uv run pytest` (pyproject `addopts` supplies `-q`; an extra `-q` would suppress the summary line and fail-closed to UNKNOWN), changed-file `uv run ruff check` + `ruff format --check`, `uv run mypy`, `git diff --check`, `git status --porcelain`.
- Every check record stores the **actual argument vector** it ran in `argv` (e.g. pytest as
  `["uv", "run", "pytest", *--pytest-target…]`), and the evidence stores `base_rev` — the rev
  the changed-file Ruff scope was computed against. The release gate independently validates
  recorded arguments against the canonical per-check contract and recomputes the changed-file
  scope; scope is never taken from a self-declared label or the overall JSON verdict.
- `--pytest-target` runs are produced with their real, non-canonical argv and are therefore
  **diagnostic-only evidence**: `run_validation.py` may report PASS for them (for the focus
  area), but the release gate rejects them for release candidacy regardless of exit code,
  passing counts, or record shape. The evidence schema stays
  `quantx.validation-evidence.v1`: `argv` and `base_rev` have always been part of it, so no
  schema bump is required for this compatibility analysis.
- Classifies every check PASS/FAIL/UNKNOWN fail-closed: unparsed output, contradictory pytest summary, timeout, or missing tool → UNKNOWN; overall = worst status.
- Both Ruff invocations (`ruff check`, `ruff format --check`) keep their **complete** stdout/stderr in `output_full` next to `exit_code`, so a formatting verdict can be re-read from the evidence instead of re-running Ruff; `output_tail` stays the bounded tail the release gate and console report consume, and remains the only form retained for the other checks. A Ruff check that did not complete (skipped, missing tool, timeout) records `output_full: null`, never an empty string, while `output_tail` still carries any captured partial output. The field is additive under the unchanged `quantx.validation-evidence.v1` schema: the release gate reads the mandatory fields it knows and ignores unknown ones.
- Verifies HEAD is unchanged before and after the run; evidence JSON (`quantx.validation-evidence.v1`) is written to `%TEMP%\quantx-validation\`.
- Exit codes: 0 PASS, 1 FAIL, 2 UNKNOWN, 3 usage/internal error. A non-zero exit is never a PASS.
- `--self-test` validates the classifier against fixture outputs and does not touch the repo.

## Evidence discipline

Require exact command/result summaries with counts. Never accept "tests pass" without command/count evidence.

## Verdicts

- **PASS** — all mandatory gates green and no blocking semantic finding.
- **BLOCKED** — any mandatory gate red or any unresolved safety/semantic blocker.

The validation worker produces evidence; it does not decide whether a defect should be fixed or whether the branch should merge. After evidence is returned, the deciding agent — not the validation run — determines whether to fix or merge.
