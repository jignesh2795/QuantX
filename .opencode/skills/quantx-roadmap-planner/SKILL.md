---
name: quantx-roadmap-planner
description: Selects and sequences the next QuantX workstream using repository evidence, dependency order, safety priority, scope isolation, and KEEP/ADAPT/EXTRACT/INTEGRATE/REJECT/DEFER decisions. Use when choosing what to build next.
metadata:
  quantx/role: planning
---

# QuantX Roadmap Planner

## Goal

Choose the next smallest high-value task rather than accumulating disconnected features.

## Decision framework

For each candidate:

- **KEEP** — existing implementation is canonical and should remain;
- **ADAPT** — reuse it with targeted hardening;
- **EXTRACT** — a stable responsibility deserves a shared boundary;
- **INTEGRATE** — an existing independent component should be connected;
- **REJECT** — conflicts with architecture/safety or duplicates work;
- **DEFER** — valuable but dependency/evidence/scope is not ready.

## Priority order

1. execution safety and correctness;
2. evidence/authority/data integrity;
3. canonical research/accounting correctness;
4. integration and operability;
5. market-specific depth with authoritative data;
6. product/UI/AI breadth.

This matches the project's active focus in `docs/STATUS.md` (execution integrity, reconciliation, recovery safety).

## Constraints

- Respect `docs/implementation/v0.1-build-order.md` sequencing and release gates.
- One focused branch/PR per coherent task; feature branches must reference an architecture decision or roadmap item.
- No broad package migration or UI/AI subsystem while an existing boundary can be hardened incrementally.
- Route durable decisions to `docs/decisions/`, sequencing to `docs/implementation/`, future work to `docs/roadmap/`.

## Output

State:

- current milestone;
- completed work;
- open gaps;
- selected next task;
- why it is next;
- exact scope boundary;
- dependencies;
- acceptance gates;
- explicitly deferred work.

Do not ask the owner to choose among options when the evidence supports a recommendation.
