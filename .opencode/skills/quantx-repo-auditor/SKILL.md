---
name: quantx-repo-auditor
description: Read-first repository audit before any non-trivial QuantX work — establishes current baseline, branch topology, existing implementations, duplication, stale docs, hidden consumers, and test-count drift. Use before planning or implementing.
metadata:
  quantx/role: audit
---

# QuantX Repository Auditor

## Objective

Establish ground truth before any implementation. Do not code during a pure audit.

## Inspect

At minimum:

- current `main` HEAD, working tree and branch state (`git status`, `git log --oneline -10`);
- `docs/STATUS.md` (validation baseline and phase);
- `docs/architecture/README.md` + the boundary docs relevant to the task;
- `docs/implementation/README.md` (discipline + build order) and `docs/roadmap/`;
- the source files relevant to the task;
- tests covering the target behavior (tests mirror the source tree);
- recent merged PRs and nearby active branches when relevant.

## Look for

- existing implementation that should be reused;
- duplicate abstractions / parallel implementations of one responsibility;
- stale docs that contradict code;
- hidden consumers of a field/type (search all usages before changing);
- semantic overlap between branches;
- scope leakage;
- unverified production claims;
- validation baselines and test-count drift (compare against `docs/STATUS.md`);
- safety-path changes wider than the stated task;
- compatibility shims that new code should not extend.

## Output

1. current authoritative baseline;
2. relevant existing components (exact paths);
3. gaps;
4. overlap/conflicts;
5. risks;
6. recommended next action;
7. what is not yet verified.
