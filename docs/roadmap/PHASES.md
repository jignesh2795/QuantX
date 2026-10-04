# QuantX Tight Phases

This is the **near-term build sequence**: small phases with one primary outcome each.

It complements (does not replace) the broader milestone map in `docs/roadmap/README.md` (M0–M6).

**Rule:** If a phase cannot be validated in a focused push, split it.

Inspired by QuantumTrade-style discipline (Phase A / Week 1 / Week 2…): narrow scope, explicit exit criteria, no mixing “implemented” with “planned.”

---

## How to use this document

- **STATUS.md** = evidence log (what is validated right now)
- **PHASES.md** = ordered work units (what to finish next)
- **Milestones (M0–M6)** = long-range product map

When a phase closes, record in STATUS:

1. Phase id and name
2. What passed
3. Explicit non-claims

---

## Current position (approximate)

Based on STATUS (execution-integrity / recovery / LIVE-control hardening):

| Phase | Likely status |
|-------|----------------|
| P0 Domain spine | Largely done |
| P1 Receipts & idempotency | Largely done |
| P2 Trading gate & reservation | Largely done |
| P3 Recovery-backed startup | Largely done |
| P4 UNKNOWN / uncertain outcomes | Largely done |
| P5 Continuation & partial fills | Largely done / hardening |
| P6 Host composition slice | Dhan slice implemented; treat as closing/hardening |
| P7+ | Not the active focus until P1–P6 exit criteria are fully signed off |

**Active work:** Finish signing off P1–P6 as a closed band before opening larger risk/research/broker breadth.

---

## Phase list

### P0 — Domain spine
**Outcome:** Stable core contracts for order, fill, position, portfolio, risk, execution.

**In scope:** Domain types, boundaries, ports direction.  
**Out of scope:** Live trading claims, UI, strategy packs.

**Exit criteria:**
- Core types and package boundaries stable
- No claim of production live trading

**Maps to:** M0 (Architecture), start of M1

---

### P1 — Receipts & idempotency
**Outcome:** Durable execution receipts; idempotent submit claims.

**In scope:** Receipt identity, durable storage of submission evidence, safe duplicate claims.  
**Out of scope:** Full recovery product, multi-broker matrix.

**Exit criteria:**
- Receipt identity is authoritative for what was submitted
- Duplicate submit claims are safe
- Tests cover happy path + duplicate claim

**Maps to:** Execution integrity track (under M1/M2 foundation)

---

### P2 — Trading gate & reservation
**Outcome:** No LIVE submit without durable gate + reservation context.

**In scope:** Durable trading-gate state, pending LIVE reservation, restart survival of gate/reservation.  
**Out of scope:** Broker-specific product workflows.

**Exit criteria:**
- LIVE submit impossible without gate + reservation on protected path
- Gate/reservation state survives process restart
- Direct LIVE dispatcher/adapter bypasses blocked

**Maps to:** LIVE control hardening

---

### P3 — Recovery-backed startup
**Outcome:** One-shot recovery before runtime is marked started.

**In scope:** ApplicationRuntime / ProductionRuntime startup lifecycle, recovery hook required, fail startup on recovery failure.  
**Out of scope:** New execution semantics inside recovery.

**Exit criteria:**
- Recovery runs once before “started”
- Failed recovery leaves startup failed
- Pure recovery path cannot broker-submit
- Restart reconstructs pending work from durable context

**Maps to:** Production composition / recovery track

---

### P4 — UNKNOWN / uncertain outcomes
**Outcome:** Uncertain broker results never complete optimistically.

**In scope:** UNKNOWN stays PENDING; no idempotency completion on uncertain evidence.  
**Out of scope:** Full reconciler product UI.

**Exit criteria:**
- Broker UNKNOWN remains durably PENDING
- Critical state does not advance on uncertain submission
- Tests cover UNKNOWN and uncertain completion paths

**Maps to:** Fail-closed LIVE behavior

---

### P5 — Continuation & partial fills
**Outcome:** Partial progress is identity-bound to authoritative receipts.

**In scope:** Continuation lineage, aggregate fill validation, idempotent continuation claims.  
**Out of scope:** Rich intrabar simulation product.

**Exit criteria:**
- Continuation claims match receipt identity (quantity, account, connection)
- Reused claims validated against authoritative evidence
- Lineage is explicit

**Maps to:** Execution integrity track

---

### P6 — Host composition slice
**Outcome:** One production host pattern with zero new execution semantics.

**In scope:** Host wires credentials/transport, account/connection identity, recovery-backed startup.  
**Out of scope:** Multi-broker matrix, CLI product, notifications.

**Exit criteria:**
- One host slice (e.g. Dhan) composes cleanly
- Host does not invent execution semantics
- Adapter boundary remains the only submit path
- Validation evidence recorded in STATUS

**Maps to:** M2 (first production broker host pattern)

---

### P7 — Pre-trade risk contracts
**Outcome:** Explicit, testable risk/policy decisions before reservation/submit.

**In scope:** Ordered pre-trade checks, reject without side effects.  
**Out of scope:** Full retail safety product (daily loss dashboards, kill-switch UX, etc.).

**Exit criteria:**
- Risk/policy layer sits before gate/reservation in the control path
- Reject path has no reservation/submit side effects
- Decisions are testable with clear reasons

**Maps to:** Control path completion (still core, not product surface)

---

### P8 — Position / portfolio on evidence only
**Outcome:** Portfolio and position state move only on accepted evidence.

**In scope:** Event/receipt-driven updates; no advance on uncertain submission.  
**Out of scope:** Portfolio analytics product.

**Exit criteria:**
- No portfolio/position advance on PENDING/UNKNOWN
- Updates consistent with receipt and continuation outcomes
- Tests cover uncertain vs accepted paths

**Maps to:** Domain consistency under execution integrity

---

### P9 — Paper / backtest fill honesty
**Outcome:** Fill models are explicit; limitations visible.

**In scope:** Model identity on receipts, blocked dispositions when data cannot support a fill, no synthetic bid/ask for candles.  
**Out of scope:** Full optimizer/walk-forward product.

**Exit criteria:**
- Selecting model identity recorded where applicable
- Fidelity/limitations explicit
- Candle path does not invent quote microstructure

**Maps to:** M3 (Simulation and Research) — contracts first

---

### P10 — Research replay guarantees
**Outcome:** Deterministic replay given same inputs and model config.

**In scope:** Replay contracts, provenance visibility, documented non-claims.  
**Out of scope:** Strategy marketplace, AI research agents.

**Exit criteria:**
- Same inputs + model config → same result
- Provenance/limitations documented
- Non-claims explicit in STATUS when closing the phase

**Maps to:** M3

---

### P11 — Next broker adapter (one only)
**Outcome:** Second adapter under the same gate/recovery rules.

**In scope:** One additional Indian broker adapter; capability checks enforced.  
**Out of scope:** Broad broker matrix, per-broker product workflows in core.

**Exit criteria:**
- New adapter does not change core execution semantics
- Same recovery/gate/UNKNOWN rules apply
- Contract tests pass at the port boundary

**Maps to:** M2 expansion

---

### P12+ — Plugins and surfaces (later)
**Outcome:** Opinionated features stay outside core.

**Examples:** CLI, strategy packs, UI, notifications, optimizers, AI agents.

**Exit criteria for any such work:**
- Lands as plugin, adapter, or separate project per VISION.md
- Core contracts remain stable

**Maps to:** M4–M6 (without pulling those responsibilities into core early)

---

## Mapping: tight phases → milestones

| Tight phases | Milestone band |
|--------------|----------------|
| P0 | M0, early M1 |
| P1–P6 | Execution integrity inside M1/M2 foundations |
| P7–P8 | Control-path completion |
| P9–P10 | M3 contracts |
| P11 | M2 expansion |
| P12+ | M4–M6 via plugins/surfaces |

---

## Closing a phase (template)

Use a short STATUS entry:

```text
Phase Px closed: <name>
Validated: <bullet list>
Non-claims: <bullet list>
Evidence: <tests / commit / notes>
Next: Py
```

Do not close a phase on partial work. Split instead.

---

## Related documents

- `docs/STATUS.md` — current validation evidence
- `docs/roadmap/README.md` — M0–M6 milestone map
- `docs/roadmap/milestones.md` — milestone exit summaries
- `docs/architecture/control-and-safety-path.md` — ordered control path
- `docs/planning/quantumtrade-transfer-map.md` — reference transfer notes
- `VISION.md` — core vs plugin boundary
