# Local Release-Validation Playbook

Status: current operating procedure. This document is the single entry point for
turning a local commit into a validated release candidate. It links to the gate
skills for policy and does not restate their rules.

Policy lives in the validation-gate skill
([SKILL.md](../../.opencode/skills/quantx-validation-gate/SKILL.md)) and the
release-gate skill
([SKILL.md](../../.opencode/skills/quantx-release-gate/SKILL.md)). This document
covers the sequence an operator runs, the evidence that sequence must leave
behind, and the verdict rules.

## What this proves — and what it does not

A passing run proves that, at one exact commit, in a clean tree, the mandatory
checks produced internally consistent evidence and the release gate accepted it.

It does not prove production readiness, broker correctness, LIVE trading safety,
or that GitHub Actions ran. Evidence is an editable local JSON file: digests and
structure detect inconsistency, not authorship.

## 1. Preflight

Run these in the primary checkout and record the output; do not edit anything yet.

```powershell
git rev-parse HEAD
git branch --show-current
git status --porcelain
git worktree list --porcelain
git stash list
git merge-base --is-ancestor <base-sha> <candidate-sha>
```

The candidate is only a candidate if the tree is clean. Tracked modifications
mean the working tree is not the commit, whatever the JSON later says.

## 2. Isolated validation worktree

Validate the commit, not the checkout you develop in. Pick a unique path that
does not collide with any existing worktree.

```powershell
git worktree add --detach "$env:TEMP\opencode\<task>-validation" <candidate-sha>
git -C "$env:TEMP\opencode\<task>-validation" rev-parse HEAD
git -C "$env:TEMP\opencode\<task>-validation" status --porcelain
```

The second command must print nothing. Run every remaining step from inside that
worktree.

## 3. Two locked dependency configurations

The suite has an optional Dhan surface. Both configurations are required; they
answer different questions.

```powershell
cd "$env:TEMP\opencode\<task>-validation"
uv sync --locked
uv sync --locked --extra dhan
```

- `uv sync --locked` proves the locked base environment works without the
  optional SDK.
- `uv sync --locked --extra dhan` proves the same with the vendor extra present.

Run the producer once per configuration, in that order. In the Dhan-disabled
configuration one optional test normally self-skips; report the skip explicitly
rather than treating it as a pass. A green run in one configuration never
substitutes for the other.

## 4. Producer evidence

```powershell
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py `
  --expected-head <candidate-sha> `
  --base <base-sha> `
  --output "$env:TEMP\quantx-validation\<task>-dhan-disabled.json"
```

Repeat with a distinct path after enabling the extra. `--expected-head` is not
optional: it is what binds the record to the commit instead of to whatever HEAD
happened to be.

The [producer script](../../.opencode/skills/quantx-validation-gate/scripts/run_validation.py)
runs six mandatory checks, named in the record as `pytest`,
`ruff-check`, `ruff-format`, `mypy`, `git-diff-check` (runs `git diff --check`),
and `worktree-integrity` (runs `git status --porcelain`). Ruff is scoped to
changed Python files against `--base`; mypy type-checks the whole `quantx`
package. A passing changed-file Ruff verdict is therefore not a repository-wide
formatting claim.

`--pytest-target` narrows the suite. A narrowed run is useful for iteration but
does not answer the release question, because the mandatory check is the full
suite. Never present a targeted run as candidate evidence.

### Full output and tails

Each record keeps two forms of the same command output:

- `output_full` — complete stdout/stderr, retained for both Ruff invocations.
  This is what a later reader inspects to decide what the command actually said.
- `output_tail` — the last 4000 characters, used by the console report and the
  release gate for compact display.

A check that did not complete (skipped, missing tool, timeout) records
`output_full: null`. An empty string is never used to imply a successful run.

Inspect the JSON before trusting the summary:

```powershell
$e = Get-Content "$env:TEMP\quantx-validation\<task>-dhan-enabled.json" -Raw | ConvertFrom-Json
$e.head_sha; $e.base_rev; $e.generated_at; $e.overall
$e.checks | Format-Table name, status, exit_code, summary
($e.checks | Where-Object name -like 'ruff*').output_full
```

Bindings to check: `repo` is this repository, `head_sha` and `expected_head` are
the candidate, `base_rev` is the intended base, and `worktree-integrity` reports
`clean tracked tree`.

An earlier command whose output was never retained cannot be reconstructed from
a summary afterwards. If a formatting question depends on a run with no stored
output, the answer is `UNKNOWN`; only a new run at a known commit resolves it.

## 5. Skill and release gates

```powershell
python .opencode/skills/quantx-skills-maintainer/scripts/skill_integrity.py --check
python .opencode/skills/quantx-skills-maintainer/scripts/skill_integrity.py --self-test
python .opencode/skills/quantx-skills-maintainer/scripts/check_trigger_assets.py
python .opencode/skills/quantx-skills-maintainer/scripts/check_trigger_assets.py --self-test
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --self-test
python .opencode/skills/quantx-release-gate/scripts/release_check.py --self-test
git diff --check <base-sha>...<candidate-sha>
```

The trigger evaluator is a static keyword-overlap proxy. Its PASS does not show
that a model would route to the right skill, and its output carries that
non-claim in writing.

Then consume the real producer records with the
[release checker](../../.opencode/skills/quantx-release-gate/scripts/release_check.py):

```powershell
python .opencode/skills/quantx-release-gate/scripts/release_check.py `
  --evidence "$env:TEMP\quantx-validation\<task>-dhan-enabled.json" `
  --expected-head <candidate-sha> `
  --output "$env:TEMP\quantx-validation\<task>-release.json"
```

The gate re-reads the record rather than trusting its `overall` field, requires
every mandatory check exactly once, cross-checks status against exit codes and
summaries, and re-verifies repository and HEAD binding. It must consume evidence
produced in this worktree at this commit; hand-edited or reused JSON invalidates
the exercise even when the gate cannot detect it.

## 6. Verdict rules

- **PASS** — both producer runs PASS at the exact candidate in a clean worktree,
  and the release gate PASSes on that evidence.
- **FAIL** — any mandatory check is FAIL, the tree is dirty, or the gate rejects
  the record.
- **UNKNOWN** — a check was skipped, timed out, could not run, or the evidence
  cannot be tied to the candidate.

A dirty tracked tree, a skipped mandatory check, a mismatched SHA, missing
evidence, or an incomplete check is never described as an all-green candidate.
Local readiness is not published PR state, and neither is a LIVE-safety claim.

## 7. Evidence retention

Keep the JSON files (`*-dhan-disabled.json`, `*-dhan-enabled.json`, and the
release report) outside the repository, together with the step output. They are
the audit trail; the worktree is disposable. Record the exact paths in the task
report.

Retention is the operator's responsibility: `%TEMP%` is not archival storage and
may be cleaned. Copy the records somewhere durable if the candidate will be
reviewed later.

## 8. Cleanup

Capture evidence before removing anything. Remove only the worktree this task
created, after confirming it holds no tracked changes and no uncommitted work
worth keeping.

```powershell
git -C "$env:TEMP\opencode\<task>-validation" status --porcelain
git worktree remove "$env:TEMP\opencode\<task>-validation"
git worktree list --porcelain
```

`git worktree remove` refuses a dirty worktree. If it refuses, inspect why and
keep the directory; do not reach for `--force` while uncommitted work might be
inside. Never remove another task's worktree, the primary checkout, stashes,
untracked operator files, or branches.

## 9. Reference run

The workflow above was used for candidate
`8400a40652f0c820e243bddbd882ea630bd5fa10` (parent `1c65dbe`, base `6692731`):

- Dhan disabled: 2045 passed, 1 skipped.
- Dhan enabled: 2046 passed.
- Ruff check and format: 4 changed Python files, exit 0.
- mypy, `git diff --check`, worktree integrity: PASS.
- Release gate: PASS, `merge-candidate HEAD: 8400a40652f0`.

Those numbers are a record of one run, not a baseline to copy. Re-run the
workflow for any new commit; counts move with the test suite and the dependency
extras.
