---
name: quantx-release-gate
description: Decides whether a QuantX branch/PR is ready to merge — test evidence, quality gates, semantic audit, safety review, scope integrity, and explicit non-claims. Use before any merge or release decision.
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
