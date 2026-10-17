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
- changed-file Ruff clean (or explicitly proven zero new in-scope findings);
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

- Consumes validation evidence (`quantx.validation-evidence.v1`, latest by default) and requires it to be **bound to the exact current HEAD**, **produced in this repository** (`evidence-repo-binding`), and to satisfy the **mandatory check contract** (`evidence-integrity`): every check record emitted by `run_validation.py` — `pytest`, `ruff-check`, `ruff-format`, `mypy`, `git-diff-check`, `worktree-integrity` — must be present exactly once as a well-formed record (`name`, `argv`, `status`, `exit_code`, `duration_s`, `summary`, `notes`, `output_tail`). Missing, duplicated, malformed, empty-named, or unsupported check entries and unsupported statuses are FAIL, never PASS; a missing check's status is never inferred from other checks. The overall verdict is recomputed from the mandatory checks; the reported summary field is never trusted alone.
- Record semantics are cross-checked against the producer's shapes: for the command checks a `PASS` requires exit 0, a `FAIL` a nonzero exit, and an `UNKNOWN` no exit code — with the single exception of `git-diff-check`, whose completed Git-error `UNKNOWN` carries a nonzero exit code and is accepted only with summary `git diff --check failed without actionable output` and note `git error`; all `git-diff-check` statuses are pinned to the producer's summaries/notes (`PASS` = `no whitespace errors`, `FAIL` = `whitespace errors found` + `git diff --check reported findings`, incomplete `UNKNOWN` = `diff check did not complete` or the skipped shape). Non-finite or negative `duration_s` values are FAIL. `pytest` records must match the exact `classify_pytest` shapes: `PASS` = exit 0, no notes, and a canonical count summary with at least one pass and no failures; `FAIL` = an exit code with either the `pytest exit code N` note or the no-tests note (the only exit-0 `FAIL`, from `pytest collected no tests`); `UNKNOWN` = either no exit code with an empty summary and non-empty notes (skipped or failed to run), or exit 0 with the failure-count-contradiction note matching failure counts, or the incomplete-pass note when the summary holds no pass count. Canonical-deviating/reordered summaries, notes that do not match the status, and any `FAIL`/`UNKNOWN` shape the producer cannot emit (for example `FAIL` without an exit code) are FAIL, never PASS. `worktree-integrity` is produced without an exit code and must not carry one; the Ruff `vacuous pass` shape (no exit code when no Python files changed) remains valid, but only with `PASS`.
- Checks: evidence presence/integrity/overall/head/repo bindings, expected-HEAD match, no tracked worktree modifications, `git diff --check <base>...HEAD` clean, informational changed-file scope vs base (`origin/main` by default).
- Exit codes: 0 PASS, 1 FAIL, 2 UNKNOWN, 3 usage/internal error. Missing, unreadable, or incomplete evidence is never PASS; consistent `UNKNOWN` validation evidence yields `UNKNOWN` (exit 2), not PASS.
- PASS means the local evidence chain is complete and internally consistent for this HEAD. Recomputation does **not authenticate** the evidence file: it is an editable local JSON artifact with no cryptographic or trusted-runner attestation, so PASS does not prove the checks were truly executed, and it does not claim production readiness, broker correctness, LIVE safety, or that CI ran. Non-claims are printed with every report.
- `--self-test` exercises the evaluator against a throwaway temp git repo.

## Merge rule

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
