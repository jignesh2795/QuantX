# Local release-validation playbook

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

Pass an immutable base SHA to `--base`, not a moving branch name. The producer
scopes changed-file Ruff against the recorded base and the release gate
recomputes that scope from it, so `origin/main` is only correct while it still
resolves to the intended base.

## 2. Isolated validation worktree

Validate the commit, not the checkout you develop in. Pick a unique path that
does not collide with any existing worktree.

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\quantx-validation\<task>" | Out-Null
git worktree add --detach "$env:TEMP\quantx-validation\<task>\wt" <candidate-sha>
git -C "$env:TEMP\quantx-validation\<task>\wt" rev-parse HEAD
git -C "$env:TEMP\quantx-validation\<task>\wt" status --porcelain
```

The last command must print nothing. Run every remaining step from inside that
worktree.

## 3. Two locked dependency configurations

The suite has an optional Dhan surface. Both configurations are required; they
answer different questions. `uv sync` makes the environment match the lockfile
and the chosen extras, so every producer run must happen immediately after its
own sync, before the other configuration is installed.

Run the two step groups below in order, from inside the worktree. The producer
command itself is described in section 4; its placement here is what makes the
measured configuration unambiguous.

### 3.1 Default configuration, then its producer run

```powershell
cd "$env:TEMP\quantx-validation\<task>\wt"
uv sync --dev --locked
```

```powershell
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py `
  --expected-head <candidate-sha> `
  --base <base-sha> `
  --output "$env:TEMP\quantx-validation\<task>\validation-default.json"
```

### 3.2 Dhan-extra configuration, then its producer run

```powershell
uv sync --dev --extra dhan --locked
```

```powershell
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py `
  --expected-head <candidate-sha> `
  --base <base-sha> `
  --output "$env:TEMP\quantx-validation\<task>\validation-dhan.json"
```

Do not run the Dhan-extra sync until the default producer has written
`validation-default.json`, and never run the default producer after the Dhan
extra has been installed.

- `uv sync --dev --locked` proves the locked base environment (test tooling
  included) works without the optional SDK.
- `uv sync --dev --extra dhan --locked` proves the same with the vendor extra
  present.

In the Dhan-disabled configuration one optional test normally self-skips; report
the skip explicitly rather than treating it as a pass. A green run in one
configuration never substitutes for the other.

## 4. Producer evidence

The producer command is the one shown twice in section 3, immediately after each
`uv sync`. `--expected-head` is not optional: it is what binds the record to the
commit instead of to whatever HEAD happened to be.

The [producer script](../../.opencode/skills/quantx-validation-gate/scripts/run_validation.py)
runs six mandatory checks, named in the record as `pytest`,
`ruff-check`, `ruff-format`, `mypy`, `git-diff-check` (runs `git diff --check`),
and `worktree-integrity` (runs `git status --porcelain`). Ruff is scoped to
changed, tracked Python files versus `--base`; mypy type-checks the whole
`quantx` package. A passing changed-file Ruff verdict is therefore not a
repository-wide formatting claim.

`--pytest-target` narrows the suite. A narrowed run is useful for iteration but
does not answer the release question: its recorded argv is not the canonical
full-suite invocation and the release gate rejects it as candidate evidence.
Never present a targeted run as candidate evidence.

### Full output and tails

Each record keeps two forms of the same command output:

- `output_full` — complete stdout/stderr, retained for both Ruff invocations.
  This is what a later reader inspects to decide what the command actually said.
- `output_tail` — the last 4000 characters, used by the console report and the
  release gate for compact display. It is the only form kept for the other
  checks.

A Ruff check that did not complete (skipped, missing tool, timeout) records
`output_full: null`. An empty string is never used to imply a successful run.
`output_full` is additive: the evidence schema stays
`quantx.validation-evidence.v1`, and a consumer that does not know the field
ignores it.

Inspect the JSON before trusting the summary:

```powershell
$e = Get-Content "$env:TEMP\quantx-validation\<task>\validation-dhan.json" -Raw | ConvertFrom-Json
$e.schema; $e.head_sha; $e.base_rev; $e.generated_at; $e.overall
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

Then consume each real producer record with the
[release checker](../../.opencode/skills/quantx-release-gate/scripts/release_check.py),
one release report per configuration:

```powershell
python .opencode/skills/quantx-release-gate/scripts/release_check.py `
  --evidence "$env:TEMP\quantx-validation\<task>\validation-default.json" `
  --expected-head <candidate-sha> `
  --base <base-sha> `
  --output "$env:TEMP\quantx-validation\<task>\release-check-default.json"
```

The gate re-reads the record rather than trusting its `overall` field, requires
every mandatory check exactly once, cross-checks status against exit codes and
summaries, re-verifies repository and HEAD binding, and recomputes the
changed-file scope from the recorded `argv` and `base_rev`. It must consume
evidence produced in this worktree at this commit; hand-edited or reused JSON
invalidates the exercise even when the gate cannot detect it.

## 6. Verdict rules

- **PASS** — both producer runs PASS at the exact candidate in a clean worktree,
  and each release gate PASSes on its matching record.
- **FAIL** — any mandatory check is FAIL, the tree is dirty, or a gate rejects
  the record.
- **UNKNOWN** — a check was skipped, timed out, could not run, or the evidence
  cannot be tied to the candidate.

A dirty tracked tree, a skipped mandatory check, a mismatched SHA, missing
evidence, or an incomplete check is never described as an all-green candidate.
Local readiness is not published PR state, and neither is a LIVE-safety claim.

## 7. Evidence retention

Keep the JSON files (`validation-default.json`, `validation-dhan.json`, and the
two release reports) outside the repository, together with the step output. They
are the audit trail; the worktree is disposable. Record the exact paths in the
task report.

Retention is the operator's responsibility: `%TEMP%` is not archival storage and
may be cleaned. Copy the records somewhere durable if the candidate will be
reviewed later.

## 8. Cleanup

Capture evidence before removing anything. Remove only the worktree this task
created, after confirming it holds no tracked changes and no uncommitted work
worth keeping.

```powershell
git -C "$env:TEMP\quantx-validation\<task>\wt" status --porcelain
git worktree remove "$env:TEMP\quantx-validation\<task>\wt"
git worktree list --porcelain
```

`git worktree remove` refuses a dirty worktree. If it refuses, inspect why and
keep the directory; do not reach for `--force` while uncommitted work might be
inside. Never remove another task's worktree, the primary checkout, stashes,
untracked operator files, or branches.

## 9. Recording a run

Every candidate records its own run; there is no shared baseline to copy. Counts
move with the test suite and the dependency extras, so a number measured at one
commit is not evidence for another.

A complete record for a candidate states, bound to its exact SHA and base:

- the per-configuration pytest result, including skipped tests and why they
  skipped;
- the changed-file count seen by Ruff and the mypy verdict;
- `git diff --check` and tracked-worktree integrity;
- the overall verdict of both producer records and both release reports;
- the exact evidence paths from section 7.

Numbers for previous candidates belong to their own task reports and evidence
files, not to this document.
