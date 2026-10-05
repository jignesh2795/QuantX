---
name: quantx-operating-model
description: Routes QuantX work so the AI makes engineering decisions and performs all non-validation work, while validation (tests/lint/typecheck) is run read-only for evidence. Defines who decides, who validates, and the normal implementation loop.
metadata:
  quantx/role: workflow
---

# QuantX Operating Model

## Operating contract

```
DECISION              → PRIMARY AI
IMPLEMENTATION        → PRIMARY AI
REVIEW                → PRIMARY AI + validation evidence
VALIDATION            → validation worker (read-only)
MERGE/RELEASE DECISION → PRIMARY AI
```

## Default ownership

The agent decides and executes:

- what happens next;
- which existing project/module to reuse;
- implementation design;
- branch and PR structure;
- documentation updates;
- fixes found by validation;
- merge readiness and merge decisions.

The owner supplies only the requested validation evidence unless explicitly taking back a decision. Never delegate architecture ownership to the validation step.

## Validation worker scope

When running validation (or when the task is explicitly VALIDATION ONLY), execution is used only to:

- checkout or create a detached temporary worktree;
- run focused tests;
- run the full suite;
- run Ruff/mypy/diff checks;
- inspect exact HEAD and diff scope;
- return an evidence report.

During validation the worker must **not** edit, fix, commit, amend, rebase, reset, revert, clean, push, or merge. The deciding agent — not the validation run — interprets evidence and decides fixes.

## Normal loop

1. Inspect repository (`quantx-repo-auditor`).
2. Decide the smallest next task (`quantx-roadmap-planner`).
3. Implement directly (`quantx-dev-workflow` + domain skill).
4. Open/update PR.
5. Give the validation worker an exact HEAD and exact commands (`quantx-validation-gate`).
6. Review the evidence.
7. Fix only evidenced blockers.
8. Revalidate the exact new HEAD.
9. Merge only when the release gate is green (`quantx-release-gate`).
10. Update canonical status/roadmap (`quantx-docs-maintainer`).

## Evidence discipline

Never accept "tests pass" without exact command and count evidence. The deciding agent interprets raw evidence; it never fabricates it.
