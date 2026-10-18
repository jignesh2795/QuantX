# Git Worktree Lifecycle (quantx-dev-workflow)

Worktrees are not disposable silently. Every temporary validation or implementation worktree must have a defined end condition, and cleanup is part of task completion.

## Create and track

1. Before creating a worktree, run `git worktree list --porcelain` and inspect existing worktrees. Reuse the task's worktree on reruns whenever practical instead of creating a new checkout for each validation command or attempt.
2. Use a task-specific path and record the purpose, branch or detached state, base SHA, and owner in the task notes/report. Validation-only work must use a detached worktree at the exact requested SHA and must not edit files.
3. Never assume a path is stale from its name or age. Identify it from Git's worktree inventory and the task that created it.

## Complete and remove

1. Before removing a worktree, capture the exact HEAD SHA, validation results, and any logs or evidence required for the final report. Inspect `git status --short`; preserve needed uncommitted evidence before removal.
2. Once no more work or validation depends on the checkout, remove the task-created worktree with `git worktree remove <path>`. Run this at the end of each completed validation/batch, whether the result passed or failed, after preserving the evidence. A pushed branch and its commits remain available after removing the local worktree.
3. Prefer normal removal. Use `git worktree remove --force <path>` only if normal removal is blocked and you have verified that (a) the exact path was created by this task, (b) its contents are disposable, and (c) no owner changes, untracked evidence, or needed logs will be lost. If any of these is uncertain, stop and report the path instead of forcing removal.
4. After removal, run `git worktree list --porcelain` again and verify the task-created path is gone. Keep an explicit list of worktrees intentionally left active for follow-up, each with a reason and cleanup condition.

## Prune safely

- `git worktree prune` removes stale Git administrative records for worktrees whose directories are already absent; it does not remove live worktree directories. Preview first with `git worktree prune --dry-run`, inspect the paths, and prune only records confirmed stale.
- Do not delete branches or commits as part of worktree cleanup. Worktree removal is not branch deletion.
- Never remove the primary checkout, a user's workspace, or a worktree owned by another active task. Do not use broad directory deletion of `Temp\opencode` or other temp roots as a substitute for `git worktree remove`.
- If the task is interrupted or further work is pending, mark the worktree `ACTIVE` and report its path, purpose, branch/SHA, and explicit cleanup condition. A completed task must not leave its temporary worktree silently behind.

## Example end-of-task checklist

```powershell
git status --short
git rev-parse HEAD
# Preserve any required logs/evidence and record the validation result.
git worktree remove "<task-worktree-path>"
git worktree list --porcelain
```
