# QuantumTrade → QuantX Transfer Map

This note records which engineering ideas from QuantumTrade (v1.4.x reference package) are already reflected in QuantX, which are partial, and which are deliberately deferred.

QuantumTrade is treated as an **engineering reference** for event-driven design, domain contracts, execution safety, and recovery mindset. It is not a code dependency and not a product template to copy.

Source reference: QuantumTrade v1.4.1 package (crypto/Binance-focused, paper-trading ready, ~773 tests in that package's claims).

---

## Already strongly reflected in QuantX

| QuantumTrade idea | QuantX status |
|-------------------|---------------|
| Event-driven + domain-driven core | Explicit in architecture direction and implemented foundations |
| Domain contracts (orders, fills, positions, portfolio, risk, execution) | Present; order lifecycle reconstruction and receipt model are active |
| Deterministic research / simulation contracts | Candle-backed deterministic backtest path exists; fidelity reporting started |
| Same-semantics intent (backtest / paper / live) | Stated goal; candle vs quote behavior is made explicit rather than faked |
| Execution integrity | Primary active track — receipts, idempotency, continuation, recovery |
| Fail-closed live behavior | Explicit: UNKNOWN receipts stay PENDING; no inference; trading gates |
| Recovery after crash / uncertain submission | Deeply implemented (pending context, restart reconstruction, isolation) |
| Safety before breadth | Matches QuantumTrade multi-layer safety mindset; focused on recovery + gates |
| Adapters outside core | Ports and adapters + capability model; Dhan is a host/adapter slice |
| Persistence of critical execution state | Durable trading-gate state, pending LIVE context, SQLite-backed stores |
| Explicit startup lifecycle | ApplicationRuntime / ProductionRuntime one-shot recovery-backed startup |
| No silent inference | Conservative recovery; authoritative receipt evidence required |

These are the areas where QuantX has absorbed QuantumTrade's engineering seriousness most clearly. In some recovery and LIVE-control details QuantX has gone further.

---

## Partially present / in progress

| QuantumTrade idea | QuantX status |
|-------------------|---------------|
| Risk engine / pre-trade checks | Domain and gates exist; not yet a full multi-layer risk stack (Risk → SafetyMonitor → KillSwitch → Portfolio) |
| Position / wallet managers | Domain foundations exist; not yet the full event-driven wallet/position reaction surface |
| Paper execution engine | Present with explicit fill models (QUOTE, BASIC_BAR); still limited (no rich intrabar, limited stop/limit realism) |
| Backtest orchestration | Deterministic path exists; not yet a full productized BacktestRunner + analytics suite |
| Fill model clarity | Strong progress (model identity on receipts, fidelity tags); still basic vs a mature execution model set |
| Market data store | Vendor-neutral MarketDataStore + dataset catalog implemented |
| Production host composition | Dhan host slice implemented; not a multi-venue host matrix |

---

## Deliberately deferred (outside core)

| QuantumTrade idea | Better home in QuantX world |
|-------------------|-----------------------------|
| Full strategy library (RSI, MACD, Supertrend, etc.) | Plugin / examples |
| Optimizer + walk-forward + Monte Carlo product surface | Research plugin or separate project |
| CLI product (qt.py-style workflows) | Plugin or separate tool |
| Telegram / notification product | Plugin |
| Binance-first (or any single-venue) product path | Adapter only; Indian brokers via adapters |
| Complete multi-layer live safety product packaging | Assemble only as far as core contracts need |
| AI agents / training surface | Future separate project |
| REST/WebSocket API product surface | Later / external |
| End-to-end "optimize → paper → live" guided workflow | Outside core; engine-first stance |

This split matches VISION.md: keep the core as infrastructure; put opinionated or audience-specific pieces in plugins or later projects.

---

## Highest-value remaining QuantumTrade-inspired work (core-aligned)

1. Stronger, explicit pre-trade risk contracts (without turning them into a retail product).
2. Clearer paper/live fill-model guarantees and limitations.
3. A minimal but solid position/portfolio reaction model driven by events.
4. Keep recovery and LIVE gates as the quality bar for any new execution path.
5. Document the ordered control/safety path (see `docs/architecture/control-and-safety-path.md`).

---

## Documentation practices worth keeping

- Phase/track deliverable discipline (what was finished and proven).
- Explicit validation evidence and explicit non-claims (already strong in STATUS.md).
- Safety/control path diagrams adapted to QuantX reality.
- Operational guidance (paper → validate → live) as documentation, not forced product workflow.

Steal the discipline, not the volume of overlapping deliverable files.

---

## Related documents

- `VISION.md` — core vs plugin boundary rules
- `docs/planning/research-and-direction.md` — broader research notes
- `docs/STATUS.md` — current implementation and validation baseline
- `docs/architecture/control-and-safety-path.md` — QuantX control path draft
