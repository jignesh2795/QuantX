# QuantumTrade → QuantX Transfer Map

This note records which engineering ideas from QuantumTrade (v1.4.x reference package) are already reflected in QuantX, which are partial, and which are deliberately deferred.

QuantumTrade is treated as an **engineering reference** for event-driven design, domain contracts, execution safety, and recovery mindset. It is not a code dependency and not a product template to copy.

**Source reference:** QuantumTrade v1.4.1 package (crypto/Binance-focused, paper-trading ready; package claims ~773 tests, multi-phase completion through paper trading).

**QuantX stance:** Indian-market-first domain model, venue-neutral core, modular monolith, plugin/adapter extensibility, no fixed user persona, no monetization plan at the current stage.

---

## 1. Why QuantumTrade matters to QuantX

QuantumTrade demonstrates a complete, deterministic, event-driven stack with:

- Explicit domain contracts and an EventBus
- Order lifecycle state machine
- Event-driven wallet and position managers
- Stateless risk checks separated from stateful managers
- Deterministic paper execution
- Multi-layer safety thinking (risk → monitor → kill → portfolio → reconcile)
- Research tools (optimizer, walk-forward, robustness, Monte Carlo)
- A full product path (CLI, strategies, Telegram, Binance live)

QuantX should absorb the **engineering seriousness** (contracts, determinism, fail-closed execution, recovery) and reject the **product packaging** (single-venue crypto workflow, strategy pack, opinionated CLI).

That split matches `VISION.md`.

---

## 2. Already strongly reflected in QuantX

These ideas are present in current architecture direction and/or implemented foundations (see `docs/STATUS.md`).

| QuantumTrade idea | What QuantumTrade did | QuantX status | Notes |
|-------------------|----------------------|---------------|-------|
| Event-driven + domain-driven core | EventBus, domain events, immutable-leaning models | Explicit architecture direction; domain foundations implemented | Keep events and contracts as the spine |
| Domain contracts | TradeIntent, MarketSnapshot, StrategyResult, order/position/wallet models | Orders, fills, positions, portfolio, risk, execution contracts present | Expand only where execution integrity needs it |
| Order lifecycle | State machine + OrderManager | Order lifecycle reconstruction and receipt model active | Receipt-centric view is a QuantX strength |
| Deterministic research / simulation | BacktestRunner with clock-driven snapshots | Candle-backed deterministic backtest path; fidelity reporting started | Prefer blocked/explicit limitations over hidden approximations |
| Same-semantics intent | Shared meaning across modes | Stated goal; candle vs quote behavior made explicit | Do not invent synthetic bid/ask for candles |
| Execution integrity | ExecutionEngine + safety layers | **Primary active track** | Receipts, idempotency, continuation, recovery |
| Fail-closed live behavior | Safety monitors + kill paths | UNKNOWN stays PENDING; no inference; trading gates | Aligns with QT safety mindset, focused on recovery |
| Recovery after uncertain outcomes | Balance reconciler, startup checks | Deep implementation: pending context, restart reconstruction, isolation | QuantX is stronger here than QT v1.4 package surface |
| Adapters outside core | Exchange/live adapters | Ports & adapters + capability model; Dhan host slice | Correct pattern |
| Persistence of critical state | SQLite state store | Durable trading-gate state, pending LIVE context, MarketDataStore | Keep persistence boundaries explicit |
| Explicit startup lifecycle | Deployment sequence discipline | ApplicationRuntime / ProductionRuntime one-shot recovery-backed startup | Do not mark runtime started if recovery fails |
| No silent inference | Conservative execution assumptions | Authoritative receipt evidence required | Non-negotiable |

**Summary:** QuantX has already integrated the hard parts of QuantumTrade's philosophy and, on recovery/LIVE control, has gone deeper.

---

## 3. Partially present / in progress

| QuantumTrade idea | Gap in QuantX | Suggested core-aligned next step |
|-------------------|---------------|----------------------------------|
| Risk engine / pre-trade checks | Gates exist; full multi-layer ladder not assembled | Define explicit pre-trade risk contracts; keep them testable and non-productized |
| Position / wallet managers | Domain foundations exist; full event-driven reaction surface thinner | Strengthen event-driven position/portfolio updates only as domain needs |
| Paper execution engine | QUOTE and BASIC_BAR fill models exist | Extend honesty of limitations; avoid rich intrabar claims until modeled |
| Backtest orchestration | Deterministic path exists | Keep orchestration minimal; analytics suites can be plugins later |
| Fill model clarity | Model identity on receipts started | Continue tagging model identity and fidelity limitations |
| Market data store | Vendor-neutral store + dataset catalog implemented | Keep store venue-neutral; brokers remain adapters |
| Production host composition | Dhan host slice implemented | Add brokers via same host/adapter pattern; do not special-case product workflows |
| Multi-layer safety ladder | Partial (gates + recovery) | Document and implement ordered path; see control-and-safety-path.md |

---

## 4. Deliberately deferred (outside core)

These belong in plugins, adapters, examples, or separate projects.

| QuantumTrade item | Why not core | Preferred home |
|-------------------|--------------|----------------|
| Strategy pack (RSI, MACD, Supertrend, DCA, etc.) | Audience/workflow specific | `examples/` or strategy plugins |
| Grid optimizer / walk-forward / Monte Carlo UX | Research product surface | Research plugin or separate tool |
| `qt.py`-style CLI workflows | Opinionated product path | CLI plugin or external tool |
| Telegram notifier | Delivery channel, not engine | Notification plugin |
| Binance-first live product path | Wrong primary market; single-venue packaging | Crypto adapter only if ever needed |
| Full packaged live safety product | Risk of becoming a retail product shell | Core contracts only; packaging later if needed |
| AI agents / training surface | Separate concern | Future project |
| REST/WebSocket API product surface | Not current focus | Later API layer on stable contracts |
| Guided optimize → paper → live workflow | Product narrative | Docs guidance only, not forced core workflow |

---

## 5. Documentation and process practices worth keeping

Take the **discipline**, not the file sprawl.

| Practice | Value | QuantX application |
|----------|-------|--------------------|
| Phase/track deliverable notes | Proves what finished | Short notes under `docs/implementation/` when a track closes |
| Explicit verification / non-claims | Prevents overselling | Already strong in STATUS.md — keep as policy |
| Safety/control path diagram | Makes control layers obvious | `docs/architecture/control-and-safety-path.md` |
| Operational sequence as guidance | Paper → validate → live thinking | Documentation only; not a mandatory product funnel |
| Changelog / checkpoint discipline | Traceability | Tie STATUS updates to real validation evidence |

Avoid creating many overlapping "deliverable" markdown files that restate the same status.

---

## 6. Highest-value remaining core-aligned work

Ordered for a correctness-first, flexible project:

1. **Document and enforce the ordered control/safety path**  
   Intent → domain validation → risk/policy → gate/reservation → submit → receipt → continuation → recovery → state update.

2. **Strengthen explicit pre-trade risk contracts**  
   Without building a full retail safety product.

3. **Keep expanding fill-model honesty**  
   Model identity, limitations, blocked dispositions when data cannot support a fill assumption.

4. **Minimal event-driven position/portfolio reactions**  
   Only as far as domain consistency requires.

5. **Preserve recovery quality as the bar**  
   Any new execution path must meet the same fail-closed and evidence rules.

6. **Broker expansion via adapters only**  
   Do not let broker-specific workflows leak into core.

---

## 7. Anti-patterns to avoid (learned from the comparison)

- Copying QuantumTrade's product surface into QuantX core
- Treating Binance/crypto assumptions as universal
- Inferring fills or completions when evidence is incomplete
- Building optimizers/CLIs/notifications before execution integrity is stable
- Letting "helpful" approximations hide model limitations
- Expanding broker count before adapter contracts and recovery guarantees are solid

---

## 8. Related documents

- `VISION.md` — core vs plugin boundary rules
- `docs/planning/research-and-direction.md` — broader research and OpenAlgo comparison
- `docs/STATUS.md` — current implementation and validation baseline
- `docs/architecture/control-and-safety-path.md` — ordered control path draft
- Production host integration docs under `docs/architecture/`
