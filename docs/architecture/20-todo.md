# QuantX Architecture TODO

> **Historical record — not current policy.** This list is a
> pre-implementation architecture work list preserved unchanged for
> provenance. Each item's disposition against the implemented system is
> audited in "TODO audit (issue #186)" below; the list itself is not current
> work. Current state: `docs/STATUS.md`. Architecture entry point:
> `docs/architecture/README.md`.

This list is intentionally limited to architecture work, not production implementation.

- Complete detailed domain model
- Complete event catalog and event versioning
- Define order/fill/position/portfolio contracts
- Define broker/data/storage ports
- Define capability manifest schema
- Define plugin manifest and trust model
- Define Strategy IR boundaries
- Define backtest/sandbox/paper/live context contracts
- Define message-bus abstraction
- Define persistence ports
- Define Indian F&O constraints
- Define control-plane API boundaries
- Define security/permission model
- Complete ADRs
- Run architecture review
- Create implementation roadmap after freeze

## TODO audit (issue #186)

**Historical audit snapshot:** `main` at `1fbddc6` (PR #214). This architecture disposition audit predates M4.1 (merged in PR #218); it remains a classification of the original architecture TODOs, not the current milestone queue. Each original item is classified **complete**, **partially complete**, **deferred/out of scope**, or **genuinely open**, with supporting evidence. No item is marked complete from filenames or historical claims alone. Current work sequencing is maintained in `docs/roadmap/README.md` and `docs/STATUS.md`.

- Complete detailed domain model — **complete**. `src/quantx/domain/`
  implements accounts, instruments, orders, order intents, portfolio,
  positions, risk, policy, capabilities, sessions, and strategy identity.
- Complete event catalog and event versioning — **partially complete**.
  The catalog exists (`src/quantx/domain/events.py`,
  `src/quantx/domain/event_bus.py`), but events carry no schema-version
  field or versioning mechanism.
- Define order/fill/position/portfolio contracts — **complete**
  (`src/quantx/domain/orders.py`, `src/quantx/domain/positions.py`,
  `src/quantx/domain/portfolio.py`).
- Define broker/data/storage ports — **complete**
  (`src/quantx/ports/broker.py`, `src/quantx/ports/market_data.py`,
  `src/quantx/ports/persistence.py`).
- Define capability manifest schema — **partially complete**. Capability
  identifiers exist (`src/quantx/domain/capabilities.py`) and plugins
  declare them (`PluginDescriptor.capabilities` in
  `src/quantx/plugins/registry.py`); there is no standalone
  manifest-schema document.
- Define plugin manifest and trust model — **partially complete**. The
  registry defines plugin identity, kind, lifecycle, and declared
  capabilities (`src/quantx/plugins/registry.py`); there is no explicit
  trust/attestation model in `src/`.
- Define Strategy IR boundaries — **complete** (`src/quantx/strategy/ir.py`
  plus compiler, registry, and runtime).
- Define backtest/sandbox/paper/live context contracts — **partially
  complete**. Backtest (`src/quantx/application/backtest.py`), paper
  (`src/quantx/execution/paper/`), and live execution guards exist; no
  named sandbox context exists in `src/`.
- Define message-bus abstraction — **complete**
  (`src/quantx/domain/event_bus.py`).
- Define persistence ports — **complete** (`src/quantx/ports/persistence.py`
  with the SQLite implementation behind `UnitOfWork`).
- Define Indian F&O constraints — **complete** (`src/quantx/india/`:
  execution rules, session calendar, rule data, instrument catalog).
- Define control-plane API boundaries — **deferred/out of scope**. No
  REST/WebSocket surface exists in `src/`; control-plane work sits behind
  Gate 5 / M5 per `docs/roadmap/decision-gates.md`,
  `docs/roadmap/milestones.md`, and `docs/roadmap/README.md`.
- Define security/permission model — **complete** as architecture
  (`docs/architecture/10-security-and-permissions.md`, capability-based
  authorization enforced through `domain/capabilities.py` and policy
  boundaries).
- Complete ADRs — **complete**. `docs/architecture/adr/` holds ADR-001
  through ADR-009; ADR-009 was marked Accepted by this reconciliation
  because its QX-03 implementation merged (PR #214 with the PR #216
  evidence-kind contract).
- Run architecture review — **complete**. `docs/architecture/15-review-checklist.md`
  exists; adversarial reviews are recorded in `docs/STATUS.md`, which states
  no outstanding adversarial finding.
- Create implementation roadmap after freeze — **complete**
  (`docs/roadmap/` milestones, decision gates, v0.1 readiness, and R1-C
  records).

Genuinely open follow-ups from this audit: event schema versioning, a
standalone capability/plugin manifest-schema document, an explicit plugin
trust model, and a named sandbox context — none of which is in the declared
v0.1 scope.
