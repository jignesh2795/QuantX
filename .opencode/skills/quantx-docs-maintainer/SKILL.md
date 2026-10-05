---
name: quantx-docs-maintainer
description: Maintains canonical QuantX STATUS, architecture, roadmap, ADR, and README docs without creating duplicate stale sources of truth. Use when updating documentation, reporting test counts, recording decisions, or writing non-claims.
metadata:
  quantx/role: documentation
---

# QuantX Documentation Maintainer

## Rules

- Verify claims against current code before editing.
- Update canonical existing docs instead of creating a new document for every batch. One source of truth.
- Preserve historical validation evidence; relabel old checkpoints rather than deleting them.
- Keep current phase/status obvious in `docs/STATUS.md`.
- Record exact commit and validation command when reporting test counts.
- Separate verified behavior from planned/deferred work; mark *implemented/current* vs *target* vs *roadmap/future*.
- Explicitly record non-claims: no production-broker end-to-end execution, no real market-data guarantee, no bundled live rule data, CI Actions not currently a gate — when applicable.
- Check cross-references and paths; never link a doc that does not exist.

## Where content belongs

| Content | Location |
|---|---|
| Current state / validation baseline | `docs/STATUS.md` |
| Architecture rules & boundaries | `docs/architecture/` (start at `README.md`) |
| Sequencing / build order / discipline | `docs/implementation/` |
| Durable architecture decisions | `docs/decisions/` (ADR format below) |
| Future milestones / decision gates | `docs/roadmap/` |
| Research & tech evaluation | `docs/research/` |

Temporary execution notes do not belong in the permanent architecture set. Historical records are not current policy unless linked from a canonical doc. Do not create one permanent document per batch unless it introduces a durable architectural decision.

## ADR-lite

Format: **Context / Decision / Consequences / Alternatives rejected.**

If an owner decision is genuinely required, mark it `PENDING OWNER DECISION` rather than inventing one. Otherwise make the recommendation and implement the chosen direction.
