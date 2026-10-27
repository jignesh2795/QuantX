# QuantX — Risk Evidence, Daily-Loss Semantics and Effective-Dated Charges

## Reconciliation of Priorities Against Current Source Tree

This note reconciles three tracked priorities against the current source tree.
It is a **planning/reconciliation document**, not an implementation. No code
was changed. Source observations below are structural (file/module inspection);
no tests were run and no CI evidence was independently verified.

Tracked issue numbers (#267, #266, #200) are not referenced anywhere in the
local repository (docs, src, tests). They are treated as external tracking IDs.

---

## Priority 1 — LIVE risk-evidence authority and request binding

**Tracking:** #267 (P1 — safety boundary)

**Verified source evidence**

- `src/quantx/domain/risk.py` defines `RiskSnapshot` as an explicit immutable
  caller-supplied state object (`observed_at`, exposures, `daily_pnl`, `equity`,
  `high_water_mark`). Its docstring states the engine never reads brokers or
  clocks; freshness is judged against an explicit `evaluated_at`.
- `PreTradeRiskEngine.evaluate_with_limits(..., snapshot=RiskSnapshot | None, ...)`
  consumes that snapshot directly. There is no `EvidenceSource`, authority, or
  request/account binding field on `RiskSnapshot` or `RiskResult`.
- `execution/preconditions/evaluator.py::execution_ready_from_evidence` converts
  integration evidence strings (`"MATCHED"`, `"PAPER"`, `"HEALTHY"`) into
  preconditions. A typed status string alone is treated as pass/fail.
- `application/execution.py` and the sanctioned LIVE composition root (not
  inspected in body) are the natural call sites.

**Gap:** A typed snapshot or status string is accepted as risk evidence without
proving it belongs to the actual account, connection, and approved order. Type
validation and freshness do not establish authority.

**Affected modules/contracts**
- `domain/risk.py` (`RiskSnapshot`, `RiskResult`, `PreTradeRiskEngine`,
  `RiskLimits`, `evaluate_with_limits`)
- `execution/preconditions/evaluator.py`, `execution/preconditions/models.py`
- `application/execution.py`
- `integrations/reconciliation/*`, `integrations/health.py`, `integrations/account_registry.py`

**Smallest next step**

1. Add an `EvidenceSource` (or `EvidenceAuthority`) enum to the risk/precondition
   layer: `BROKER`, `RECONCILED`, `SNAPSHOT`, `UNKNOWN`.
2. Add an `evidence_source` field to `RiskSnapshot` (or to the evaluation
   input), defaulting to `SNAPSHOT` for caller-supplied state.
3. Gate `evaluate_with_limits` approval on `evidence_source in {BROKER,
   RECONCILED}`; `SNAPSHOT`/`UNKNOWN` → fail closed (REJECT) with a stable
   reason code.
4. In `execution_ready_from_evidence`, distinguish a reconciled status from a
   merely "MATCHED" status string; require reconciliation evidence for LIVE.

**Negative tests (acceptance)**

- Snapshot-only input → REJECT, reason cites evidence authority.
- `UNKNOWN` source → REJECT.
- Foreign/stale/contradictory evidence → REJECT before reservation/submission.
- `RECONCILED` with reconciliation status not `MATCHED` → REJECT.
- Existing approved path still approves when evidence is broker/reconciled and
  fresh.

**Non-goals:** no broker adapter changes; no SEBI compliance layer (ADR-010);
no new subsystem; do not reimplement #197 market-pack pre-trade checks.

---

## Priority 2 — Explicit daily-loss semantics

**Tracking:** #266 (P1 — risk correctness)

**Verified source evidence**

- `domain/risk.py` `RiskLimits.max_daily_loss` and `evaluate_with_limits`
  (lines ~331–345) use `snapshot.daily_pnl` only, with an explicit comment:
  "Only already-realized daily P&L counts; the proposed order is never treated
  as realized loss."
- `RiskSnapshot` carries `daily_pnl`, `equity`, `high_water_mark` but no
  unrealized/mark-to-market field. `max_drawdown` uses equity vs high-water-mark.
- `execution/post_trade_risk.py`, `execution/post_trade_enforcement.py`,
  `execution/portfolio_valuation.py`, `execution/valuation.py` exist but their
  bodies were not inspected.

**Gap:** Daily-loss enforcement uses realized P&L only and may not account for
losses on open positions. Realized vs unrealized/mark-to-market semantics are
not defined separately.

**Affected modules/contracts**
- `domain/risk.py` (`RiskLimits`, `RiskSnapshot`, `evaluate_with_limits`,
  `_risk_number`)
- `domain/finance.py` (money/Decimal types)
- `execution/post_trade_risk.py`, `execution/post_trade_enforcement.py`
- `execution/portfolio_valuation.py`, `execution/valuation.py`, `execution/accounting.py`

**Smallest next step**

1. Add `unrealized_pnl` (or `mark_to_market_pnl`) to `RiskSnapshot` as an
   optional Decimal, defaulting to `None` (fail closed when a limit needs it).
2. Define separately: realized daily P&L, unrealized/mark-to-market P&L,
   valuation time, and drawdown. Audit sources before introducing any shared
   calculation.
3. Add a distinct limit or evaluation path for unrealized loss (do not conflate
   with `max_daily_loss` unless policy explicitly says so).

**Negative tests (acceptance)**

- Profitable realized day with material unrealized loss → behavior documented
  (either rejected under new limit or explicitly excluded with reason).
- Mark-to-market reversal → decision changes deterministically.
- Stale/missing required inputs → fail closed.
- Policy disabled (`max_daily_loss is None`) → unchanged behavior.

**Guardrail:** Do not create a universal risk function. Reuse only genuinely
identical calculations; preserve the intentional distinction between pre-trade,
post-trade, and projected-state evaluation.

**Non-goals:** no new risk limits beyond defining semantics; no change to
existing thresholds; no reimplementing #197/#196.

---

## Priority 3 — Effective-dated Indian market charges

**Tracking:** #200 (P2 — market realism)

**Verified source evidence**

- `execution/charges.py` docstring explicitly states it "deliberately does not
  encode broker tariffs, taxes, exchange schedules, or other market-specific
  rules." It provides `ChargeModel` (Protocol), `PercentageBpsChargeModel`,
  `ChargeBreakdown` with `model_id`, `model_version`, `provenance`.
- `india/execution_rules.py`, `india/rule_data.py`, `india/domain.py` exist.
- `research/point_in_time.py`, `research/provenance.py` exist and provide
  point-in-time and provenance patterns.
- `docs/architecture/52-transaction-cost-and-charges.md` exists (not inspected).

**Gap:** No effective-dated Indian tariff schedule exists; charges are configured,
not authoritative/effective-dated. Paper/backtest/live paths could silently use
estimated tariffs.

**Affected modules/contracts**
- `execution/charges.py` (`ChargeModel`, `ChargeBreakdown`, `ChargeComponent`)
- `india/execution_rules.py`, `india/rule_data.py`, `india/domain.py`
- `research/market_rules.py`, `research/venue_adapters.py`
- `research/point_in_time.py`, `research/provenance.py`
- `execution/portfolio_valuation.py`

**Smallest next step**

1. Specify schedule identity, effective-time selection, authoritative source
   metadata, and calculation basis (docs first, no code).
2. Implement one bounded schedule slice behind the existing `ChargeModel`
   interface, adding `effective_from`/`effective_to` and `source_ref` to a new
   charge model (not replacing `PercentageBpsChargeModel`).
3. Golden calculations for dates on either side of a tariff change.

**Negative tests (acceptance)**

- Charge lookup for unsupported date → fail closed (no silent substitution).
- Unsupported product/segment combination → explicit failure.
- Paper, backtest, and any live-receipt accounting path uses the applicable
  version with exact Decimal arithmetic and recorded provenance.

**Non-goals:** no scraping/live-fetching of tariffs (explicit inputs only);
no new charge types; no new accounting engine; do not reimplement #197/#196.

---

## Cross-cutting constraints

- Preserve fail-closed behavior; UNKNOWN must never become PASS.
- Preserve existing execution/recovery contracts absent a reproduced invariant
  violation.
- Do not reimplement completed #197 market-pack pre-trade checks or #196
  StrategyContext work.
- Do not introduce a new accounting engine, universal risk subsystem,
  broker-side compliance layer, or distributed service.
- Distinguish structural inspection (this document), locally executed tests
  (none performed here), and independently verified CI evidence (none
  referenced).
- Update canonical roadmap/status only after implementation scope and acceptance
  criteria are reconciled against the current source tree.

## Ranked implementation sequence

1. Priority 3 (effective-dated charges) — smallest, self-contained, unblocks
   accurate P&L for Priority 2.
2. Priority 1 (risk-evidence authority) — safety boundary; gates pre-trade
   checks on authoritative evidence.
3. Priority 2 (daily-loss semantics) — depends on Priority 1 inputs and
   Priority 3 charges; largest; do last.

## Premature / duplicate / out-of-scope

- Reimplementing #197 or #196 (completed).
- A new `risk/` top-level package or universal risk subsystem.
- Broker-side SEBI compliance (ADR-010 boundary).
- UI/Flow, AI/agents, scheduling, CLI, distributed services (out of M4.1).
- A new accounting engine or replacing `execution/charges.py`.
- New charge types or new risk limits before semantics are settled.
- Treating this document as verified evidence — it is structural inspection
  only; inspect bodies and run tests before implementing.
