---
name: quantx-migration-consolidation
description: Safely consolidates QuantX branches and implementations — preserving useful work from resets, analyzing branch overlap, and choosing KEEP/CHERRY-PICK/REBUILD/EXTRACT/REJECT/ARCHIVE so stale or duplicate lines never re-enter main. Use for branch cleanup, recovery, or duplicate-code consolidation.
metadata:
  quantx/role: migration
---

# QuantX Migration & Consolidation

## Before any destructive operation

Preserve potentially useful work with a recovery branch or immutable reference. Do not reset a branch until the target and all unique commits are identified.

## Analyze branches by

- common base;
- unique commits;
- file scope;
- semantic purpose;
- overlap/conflict;
- test evidence;
- whether the work is already present in `main`.

## Recovery rule

If work was orphaned, first preserve the SHA on a named recovery branch. Then determine whether it contains:

- valuable unique work;
- a stale revert;
- superseded implementation;
- unrelated work accidentally committed on the wrong branch.

Never restore an entire orphaned commit blindly.

## Consolidation decisions

For each branch/commit choose: **KEEP / CHERRY-PICK / REBUILD / EXTRACT / REJECT / ARCHIVE.**

Document why. `main` must remain free of accidental parallel implementations.

## Code-level consolidation

When consolidating duplicate code rather than branches:

- one canonical implementation per responsibility (a duplicate is a defect, not a fallback);
- move new code to target boundaries; move/modify existing files when next touched — no risky repository-wide renames;
- avoid structural migration while execution-integrity work is active;
- keep clearly-labeled compatibility shims intact until their consumers migrate;
- never merge deliberately distinct modules (e.g. `execution/order_lifecycle.py` vs `execution/receipts/lifecycle.py`);
- a module earns its own subpackage when it has independent invariants, tests, or a plugin boundary.
