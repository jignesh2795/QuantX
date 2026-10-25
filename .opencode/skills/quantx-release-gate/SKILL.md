---
name: quantx-release-gate
description: Use before any merge or release decision — decides whether a QuantX branch/PR is ready: test evidence, quality gates, semantic/safety audit, scope integrity, explicit non-claims, plus the executable release-check script.
metadata:
  quantx/role: release
---

# QuantX Release Gate

## Mandatory evidence

Require all of the following, for the **exact HEAD being merged**:

- exact validated HEAD;
- focused tests appropriate to the task;
- full suite green;
- changed-file Ruff lint and format clean (or explicitly proven zero new in-scope findings);
- strict mypy on changed production files where required;
- `git diff --check` clean;
- semantic audit;
- safety audit when execution behavior is touched (control-path review from `quantx-core-governance`);
- exact scope audit (no scope leak);
- repository integrity (`git status --porcelain` clean apart from intended changes).

## Executable release check

`scripts/release_check.py` verifies the merge candidate read-only and reports PASS/FAIL/UNKNOWN fail-closed:

```powershell
python .opencode/skills/quantx-release-gate/scripts/release_check.py --expected-head <sha>
python .opencode/skills/quantx-release-gate/scripts/release_check.py --evidence <validation-json>
python .opencode/skills/quantx-release-gate/scripts/release_check.py --self-test
```
- Consumes validation evidence (`quantx.validation-evidence.v1`, latest by default) and
  requires it to be **bound to the exact current HEAD**, **produced in this repository**
  (`evidence-repo-binding`), and to satisfy the **mandatory check contract**
  (`evidence-integrity`): every check record emitted by `run_validation.py` — `pytest`,
  `ruff-check`, `ruff-format`, `mypy`, `git-diff-check`, `worktree-integrity` — must be
  present exactly once as a well-formed record (`name`, `argv`, `status`, `exit_code`,
  `duration_s`, `summary`, `notes`, `output_tail`). Missing, duplicated, malformed,
  empty-named, or unsupported check entries and unsupported statuses are FAIL, never PASS;
  a missing check's status is never inferred from other checks. The overall verdict is
  recomputed from the mandatory checks; the reported summary field is never trusted alone.
- **Command scope** (`command-scope`): shape-consistent evidence can still record the wrong
  command, so every PASS-status mandatory record's actual `argv` is validated against the
  producer's canonical contract, and the changed-file scope is recomputed from the
  candidate/base comparison:
  - `pytest` must be exactly `["uv", "run", "pytest"]`. A targeted invocation such as
    `["uv", "run", "pytest", "tests/unit/execution/"]` never satisfies the mandatory
    full-suite check — regardless of exit code, passing count (460 or 2045, no count
    threshold is used), or otherwise valid record shape. The diagnostic FAIL names argv and
    preserves the recorded test summary as diagnostics only; it cannot be confused with
    missing or incomplete evidence because the record itself stays well-formed.
  - `ruff-check` / `ruff-format` must list exactly the expected changed-Python-file set
    (`ruff format` also requires `--check` in canonical position). The vacuous pass
    (`argv []`, summary `vacuous pass`) is accepted only when the recomputed changed-Python
    set is empty. The evidence's `base_rev` must resolve to the same commit as the
    release-gate base; evidence validated against a different base is a scope-mismatch FAIL
    and never establishes scope.
  - `mypy` must be `["uv", "run", "mypy"]`, `git-diff-check` must be
    `["git", "diff", "--check"]` (the gate's independent committed-range whitespace check
    is unaffected), and `worktree-integrity` must be `["git", "status", "--porcelain"]`.
  - Scope violations are reported by the dedicated `command-scope` check as a specific
    FAIL; an unresolvable gate base degrades that check to UNKNOWN, never PASS. The
    evidence schema remains `quantx.validation-evidence.v1` — `argv` and `base_rev` were
    already mandatory fields, so no schema bump is required.
- Record semantics are cross-checked against the producer's shapes: for the command checks a `PASS` requires exit 0, a `FAIL` a nonzero exit, and an `UNKNOWN` no exit code — with the single exception of `git-diff-check`, whose completed Git-error `UNKNOWN` carries a nonzero exit code and is accepted only with summary `git diff --check failed without actionable output` and note `git error`; all `git-diff-check` statuses are pinned to the producer's summaries/notes (`PASS` = `no whitespace errors`, `FAIL` = `whitespace errors found` + `git diff --check reported findings`, incomplete `UNKNOWN` = `diff check did not complete` or the skipped shape). Non-finite or negative `duration_s` values are FAIL. `pytest` records must match the exact `classify_pytest` shapes: `PASS` = exit 0, no notes, and a canonical count summary with at least one pass and no failures; `FAIL` = an exit code with either the `pytest exit code N` note or the no-tests note (the only exit-0 `FAIL`, from `pytest collected no tests`); `UNKNOWN` = either no exit code with an empty summary and non-empty notes (skipped or failed to run), or exit 0 with the failure-count-contradiction note matching failure counts, or the incomplete-pass note when the summary holds no pass count. Canonical-deviating/reordered summaries, notes that do not match the status, and any `FAIL`/`UNKNOWN` shape the producer cannot emit (for example `FAIL` without an exit code) are FAIL, never PASS. `worktree-integrity` is produced without an exit code and must not carry one; the Ruff `vacuous pass` shape (no exit code when no Python files changed) remains valid, but only with `PASS`.

- Checks: evidence presence/integrity/overall/head/repo bindings, `command-scope` (canonical
  recorded argv per mandatory check plus recomputed changed-file scope vs the release base),
  expected-HEAD match, no tracked worktree modifications, `git diff --check <base>...HEAD`
  clean, informational changed-file scope vs base (`origin/main` by default).
- Exit codes: 0 PASS, 1 FAIL, 2 UNKNOWN, 3 usage/internal error. Missing, unreadable, or
  incomplete evidence is never PASS; consistent `UNKNOWN` validation evidence yields
  `UNKNOWN` (exit 2), not PASS.
- PASS means the local evidence chain is complete and internally consistent — including
  recorded command arguments — for this HEAD. Recomputation does **not authenticate** the
  evidence file: it is an editable local JSON artifact with no cryptographic or
  trusted-runner attestation, so argv validation does not prove the checks were truly
  executed (a fabricated argv passes the same way), and it does not claim production
  readiness, broker correctness, LIVE safety, or that CI ran. Non-claims are printed with
  every report.
- `--self-test` exercises the evaluator against a throwaway temp git repo.

## Merge rule

Targeted or diagnostic evidence (including any `--pytest-target` run) may exist
independently but never satisfies the mandatory full-suite pytest contract above.

Merge only when:

- mandatory tests are green;
- quality gates are green, or repository policy explicitly permits pre-existing/out-of-scope findings;
- no new in-scope lint/type failures remain;
- no unresolved safety blocker exists;
- no scope leak exists;
- PR claims are supported by evidence;
- `uv.lock` is committed if dependencies changed.

## Never merge on assumption

- A green focused suite does not excuse a red full suite.
- A green test suite does not excuse an authority/safety defect.
- A clean diff does not prove runtime behavior.
- Passing local validation does not claim production-broker behavior — no production-broker end-to-end execution has been performed.

Preserve these distinctions explicitly in the merge decision.
