# QuantX — Risk Evidence, Daily-Loss Semantics and Effective-Dated Charges

> **Status and sequencing notice (2026-10-27):** This is a structural source-tree review, not an implementation or an approved API design. Its original final ranking is superseded by `docs/planning/quantx-work-program-2026-10.md` and the current acceptance criteria in issues #267, #266 and #200. In particular, an `EvidenceSource` enum or a `BROKER`/`RECONCILED` label alone does **not** establish trusted provenance; do not use the historical sketch below to grant LIVE approval. If trustworthy request-bound evidence is not available, the sanctioned LIVE path must remain blocked. No tests were run by this document's original review.


## Reconciliation of Priorities Against Current Source Tree

This note reconciles three tracked priorities against the current source tree.
It is a **planning/reconciliation document**, not an implementation. No code
was changed. Source observations below are structural (file/module inspection);
no tests were run and no CI evidence was independently verified.

At the time this note was first drafted, issue IDs (#267, #266, #200) were not
embedded in the then-reviewed local source snapshot; they are now tracked in the
current master work programme and remain the canonical external issue records.

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
- `execution/post_trade_risk.py` also checks realized daily P&L only. Its
  `PostTradeRiskEnforcer` is wired into `execution/paper_session.py`; the
  inspected LIVE composition roots do not install this PAPER post-trade enforcer.
- `execution/portfolio_valuation.py` can return a partial snapshot with
  `completeness="INCOMPLETE"`; callers must not consume that partial aggregate
  as complete risk equity. `HistoricalAccountStateTracker` instead withholds
  equity/unrealized P&L when required marks are missing.

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

## Current sequence and design corrections (2026-10-27)

The original draft ranked charges before risk evidence because the charge slice looked
self-contained. That ordering is superseded by the current work programme:

1. **#267 — LIVE risk-evidence authority and exact request binding.** This is the
   next implementation priority. Bind evidence to the approved order and exact
   account/portfolio/broker connection, verify freshness/completeness and source
   authority, and reject missing, stale, foreign, contradictory or unverifiable
   inputs before durable reservation or submission. Do not trust a returned
   dataclass, status string, or self-declared enum as proof of provenance. If a
   trustworthy adapter is not yet available, the sanctioned LIVE path stays blocked.
2. **#266 — daily-loss semantics.** Define realized versus unrealized/mark-to-market
   P&L, valuation cut, evidence freshness and reversal behavior without silently
   redefining the existing realized-only field. Coordinate with #267's evidence
   contract; no source change until the semantics and negative-path acceptance tests
   are explicit.
3. **#200 — effective-dated India charges.** Continue through the contract-only slice
   specified in `india-market-charges-design.md`; only verified schedule entries may
   become production data. Unresolved GST/stamp-duty effective applicability remains
   unavailable rather than guessed. This is a separate market-realism milestone, not
   a substitute for #267 and not a reason to delay safety evidence work.
4. **#198, #182 and #202 — deterministic time and validation assurance.** Complete
   remaining clock inventory; establish measured package-specific coverage floors;
   and separately audit module reachability and Dhan transport line/branch coverage.

Current sequencing and issue acceptance criteria take precedence over the original
implementation suggestions elsewhere in this structural review. No source/test result
is claimed by this update.

## Premature / duplicate / out-of-scope

- Reimplementing #197 or #196 (completed).
- A new `risk/` top-level package or universal risk subsystem.
- Broker-side SEBI compliance (ADR-010 boundary).
- UI/Flow, AI/agents, scheduling, CLI, distributed services (out of M4.1).
- A new accounting engine or replacing `execution/charges.py`.
- New charge types or new risk limits before semantics are settled.
- Treating this document as verified evidence — it is structural inspection
  only; inspect bodies and run tests before implementing.


---

## Issue #266 follow-up — account-equity accounting basis and Dhan evidence (2026-10-30)

**Reviewed baseline:** `main` at `6871c46202d4b9256b14d6b5945703c68f0f7de5`.

This is a current source-and-documentation reconciliation. It is a design proposal,
not an implementation or LIVE authorization. The accounting definitions below
are recommendations; Dhan-specific API behavior is stated only to the extent
that the published DhanHQ v2 documentation and Dhan Support material describe it.

### 1. Current QuantX implementation

- `RiskSnapshot.daily_pnl` is the only daily-P&L input consumed by
  `PreTradeRiskEngine.evaluate_with_limits`. Its enabled `max_daily_loss`
  check is explicitly realized-only. Missing/invalid values reject.
- `RiskSnapshot` has `equity` and `high_water_mark` for the separate
  `max_drawdown` check, but no dedicated account-level realized/unrealized
  decomposition or session-start equity baseline.
- `PostTradeRiskEngine` also checks only realized daily P&L. The inspected
  `PostTradeRiskEnforcer` consumer is `PaperSession`; this is not evidence of
  a LIVE mark-monitoring or LIVE gate-enforcement path.
- `FillAccounting`, `CashLedger`, `MarkToMarketValuator`,
  `PortfolioValuator`, and `HistoricalAccountStateTracker` already provide
  broker-neutral fill, cash, mark, and simulated account-state building blocks.
  `HistoricalAccountStateTracker` explicitly rejects LIVE capital.
- `PortfolioValuator` reports incomplete coverage but still exposes a
  `PortfolioSnapshot`; any LIVE risk consumer must check completeness before
  using its aggregate values. `HistoricalAccountStateTracker` withholds
  equity/unrealized values when cash or required position marks are unavailable.
- `integrations/reconciliation/account.py::AccountFinancialState` is the
  nearest existing broker-neutral account observation contract. It currently
  has account/connection identity, source, observation time, currency and
  optional equity/cash/margin values, but does not express an equity basis,
  whole-account valuation coverage, trusted capture time, or session baseline.
- SQLite schema v8 has no account-equity observations, risk-session baselines,
  external capital-flow event ledger, or durable high-water-mark state.

PR #285 adds HMAC-bound supplemental per-position P&L rows. It does not provide
account/day P&L, a complete account equity value, baseline state, or an
application-facing account-P&L read service. In the current Dhan source,
`funds.sod_limit` is mapped into `domain.finance.AccountFinancialState.cash_balance`,
while `funds.available_balance` is mapped into available cash, margin available
and buying power. These are current funds mappings, not proof that either field
is net-liquidation equity or that `sodLimit` is a valid session-equity baseline.
The sanctioned Dhan authority
still declares `DAILY_PNL`, `EQUITY`, and `HIGH_WATER_MARK` unsupported and
returns unavailable before invoking the source collector.

### 2. Current official Dhan evidence surface

Published DhanHQ v2 docs describe these relevant resources:

| API | Documented data | What it does not establish by itself |
|---|---|---|
| `GET /positions` | Open position rows for the day, including F&O carry-forward; realized/unrealized profit; day and carry-forward buy/sell quantities and values | A canonical daily account P&L definition or complete account equity |
| `GET /holdings` | Demat holdings, delivered/T1 quantities, collateral quantity and average cost | Current holding market value, account-wide net liquidation equity, or all liabilities |
| `POST /marketfeed/ltp` / `ohlc` / `quote` | Batched market observations; up to 1,000 instruments per request and documented 1 request/second limit | Complete valuation unless every held/position instrument is known and a usable current mark is available |
| `GET /trades/{from-date}/{to-date}/{page}` | Paginated historical trades, exchange trade IDs, quantities, prices, trade timestamps and listed charge fields (SEBI tax, STT, brokerage, service tax, exchange transaction charges, stamp duty) | A complete account cash/equity snapshot or all non-trade capital movements, including non-cash asset transfers |
| `GET /ledger?from-date=...&to-date=...` | Debit/credit entries, narration, voucher date, voucher number and running balance | An intraday transaction timestamp or a published complete classification taxonomy covering cash and non-cash external capital flows |
| `GET /fundlimit` | Available balance, start-of-day limit/balance, collateral, receivables, utilized amount, blocked payout and withdrawable balance | A documented net-liquidation equity measure or a formal relation that makes these fields equivalent to account equity |

Important Dhan Support distinctions:

- Trader's Diary realized P&L is described as gross P&L from positions closed
  during the day, calculated using FIFO/speculation basis; its net realized
  P&L adjusts for taxes and brokerage. Open positions are excluded.
- Dhan separately explains that the Position tab uses average buy/sell prices
  and includes open positions, while Trader's Diary uses closed positions and
  FIFO/speculation. The two can differ.
- Dhan says its Trader's Diary adjusts for corporate actions, share transfers
  and IPO allotments. A reconstruction from trade fills alone therefore does
  not reproduce the documented Trader's Diary accounting basis.

The v2 Positions schema calls `realizedProfit` booked P&L and
`unrealizedProfit` P&L standing on open positions; its row also exposes
carry-forward and day quantities/values. The v2 release notes state that these
position P&L fields were made real-time. Neither the Positions schema nor the
support articles establish that `realizedProfit` is identical to Trader's
Diary FIFO daily realized P&L, or that `unrealizedProfit` is only the current
session's change rather than the full open-position amount. Do not infer either
equivalence.

The Ledger response documents `voucherdate` as a transaction date and shows
no transaction-time field. That is insufficient to assign same-day deposits
or withdrawals precisely to an intraday equity observation. The support
material also mentions share transfers and IPO allotments in Trader's Diary
adjustments; the published Ledger/Trade History schemas do not establish a
complete, timestamped feed of those non-cash capital events. The public v2
Statement API documents Ledger and Trade History; it does not document an API
that returns the Trader's Diary summary.

**Official references (reviewed 2026-10-30):**

- [DhanHQ v2 Portfolio and Positions](https://dhanhq.co/docs/v2/portfolio/)
- [DhanHQ v2 Funds and Margin](https://dhanhq.co/docs/v2/funds/)
- [DhanHQ v2 Statements](https://dhanhq.co/docs/v2/statements/)
- [DhanHQ v2 Market Quote](https://dhanhq.co/docs/v2/market-quote/)
- [DhanHQ v2 Releases](https://dhanhq.co/docs/v2/releases/)
- [Dhan Support — Trader's Diary](https://dhan.co/support/statements-and-ledger/trader-s-diary/what-is-a-trader-s-diary-and-how-does-it-work/)
- [Dhan Support — Position tab versus Trader's Diary](https://dhan.co/support/statements-and-ledger/trader-s-diary/why-does-my-profit-and-loss-p-and-l-reflecting-different-in-trader-s-diary-as-compared-to-the-position-tab/)
- [Dhan Support — Trader's Diary updates](https://dhan.co/support/statements-and-ledger/trader-s-diary/how-is-the-trader-s-diary-updated/)

### 3. Gaps in the current QuantX Dhan adapter

The present `DhanTransport` exposes profile, fund limits, positions,
holdings, per-instrument quote snapshots and candles. It does not expose the
documented Ledger or historical Trade History resources, nor the batched
Market Quote endpoints.

`DhanPositionSnapshot` normalizes net quantity, average/cost price, product,
position type, realized P&L and unrealized P&L, but does not preserve the
documented carry-forward/day quantity and value fields. `DhanHoldingSnapshot`
preserves holdings quantities and average cost but no current mark. The
`DhanRiskEvidenceSource` maps only the deployment's configured instrument
registry; an unmapped row makes row-level P&L incomplete and unmapped
holdings/positions prevent complete exposure aggregation.

These are bounded adapter capability gaps, not proof that Dhan cannot provide
the underlying raw data. A later adapter slice could preserve Ledger, Trade
History, day/carry-forward position fields, and batch marks as supplemental
evidence. It must not label those records as daily account P&L or net
liquidation equity without a separately established accounting rule.

### 4. Recommended broker-neutral accounting contract

**Decision proposal:** retain the current realized-only `daily_pnl` meaning.
Introduce a distinct *session equity P&L* measure only when a complete
account-level equity observation and an authoritative session baseline exist.

For one account risk scope and one currency:

```
session_equity_pnl(t)
    = current_net_liquidation_equity(t)
    - session_open_net_liquidation_equity
    - net_external_capital_contributions(session_open, t]
```

External capital contributions are positive; withdrawals/dispositions are
negative. This includes cash movements and genuine non-cash asset transfers
into or out of the measured account scope, valued at their effective time from
explicit evidence. Internal transfers wholly inside the measured scope are
neutral. Corporate actions, splits, bonuses, dividends, settlements, IPO
purchases and product conversions must be reconciled as their own accounting
events; do not automatically classify them as external contributions. Only
capital or assets entering/leaving the measured scope are flow adjustments. Subtracting signed net contributions prevents a deposit or transferred
holding from appearing as trading profit, and a withdrawal or asset transfer
out from appearing as trading loss. Trade fees, taxes, financing and other
expenses already reflected in current account equity must not be subtracted a
second time. If the selected equity basis excludes an expense,
that exclusion must be explicit and the expense must be included once.

The corresponding loss is the negative signed session P&L. A separately
configured limit (provisionally `max_daily_equity_loss`) compares that loss
with its own threshold. Do not silently redefine `daily_pnl` or add the
realized and unrealized fields from PR #285.

The smallest reusable contract should reuse/extend the existing
`integrations/reconciliation/account.py::AccountFinancialState` seam rather
than create a second accounting engine. The evidence contract needs, at
minimum:

1. **Identity and scope:** canonical account ID, broker-connection ID, and an
   explicit risk scope. Account-level broker equity must not silently be used
   as strategy-portfolio equity.
2. **Equity semantics:** a typed basis meaning *net liquidation equity* in one
   declared valuation currency—not available cash, buying power, margin limit,
   `sodLimit`, or gross market exposure.
3. **Two instants:** provider/source `observed_at` and trusted host
   `captured_at`. A recent capture time cannot make an old price or balance
   current.
4. **Coverage and completeness:** explicit evidence that the complete
   in-scope asset/liability universe is included. Missing/unmapped holdings,
   positions, collateral, MTF liabilities, currency conversion, marks or
   balance components make equity unavailable. A provider's self-declared
   COMPLETE string is not authority; the application-owned registered source
   and expected scope must validate coverage.
5. **Capital-flow records:** stable source transaction identity, signed
   Decimal Money value, currency, external-versus-internal classification,
   effective timestamp and observation timestamp. Non-cash asset transfers
   additionally require canonical asset identity, quantity, and an explicit
   valuation basis/source at the transfer time. Unknown classifications or
   non-cash valuations, missing pages, date-only timing where intraday
   attribution is required, or contradictory balances make the adjustment
   incomplete.
6. **Provenance:** source identity, source record references/fingerprint,
   per-component observations, and explicit unavailable/contradictory reasons.

A separate durable session-baseline record is required, keyed by account,
connection, risk scope, market calendar/session identity, currency and
accounting-policy version. It must retain the baseline equity, source
observation identity, source observation time and trusted capture time. The
baseline is write-once for a session; restart must reload the same baseline,
not silently create a new one. If the application starts after the session
boundary and cannot obtain the true session-open baseline, the metric is
UNKNOWN and the LIVE risk check rejects.

A small dedicated persistence repository is required for session baselines
(and later HWM state). It should not overload the existing execution
idempotency/receipt UnitOfWork, whose records and transaction purpose are
different. No SQLite schema change is approved by this design note.

### 5. Boundaries and policy interactions

- **Realized daily P&L:** preserve its existing meaning and tests. It can remain
  an independent, stricter limit.
- **Session equity P&L:** measures change in complete account equity, adjusted
  for external flows. It is not the sum of position row P&L.
- **High-water mark / drawdown:** keep separate. A durable drawdown basis must
  define how external deposits/withdrawals adjust the high-water mark; do not
  treat raw account contributions as investment profit or loss. This issue
  does not redefine current `max_drawdown`.
- **Session calendar:** use an explicit market calendar/session identity, not
  wall-clock midnight. A baseline must correspond to the actual session
  boundary and selected account risk scope.
- **Evidence freshness:** all components must be no older than the risk
  policy permits and must not be future-dated. Currency conversion requires
  explicit, fresh FX evidence; otherwise reject.
- **Enforcement cadence:** the existing LIVE path evaluates risk before a
  dispatch. That blocks a new order when the submitted risk snapshot breaches
  the limit; it is not an autonomous mark-to-market monitor and does not
  liquidate existing positions. If automatic durable gate trips between
  orders are required, they need a separately designed monitored valuation
  path. The current Dhan market-data adapter is snapshot-only and explicitly
  rejects streaming subscription.
- **Fail closed:** missing baseline, incomplete equity, stale marks, incomplete
  capital-flow history, unsupported equity basis, or unverified scope means the
  new metric is unavailable and the LIVE check rejects. Never default to zero
  or initialize the baseline from a post-trading first observation.

### 6. Dhan-specific feasibility verdict

Dhan's documented data surface is materially richer than QuantX currently
normalizes: positions include carry-forward/day breakdowns, the historical
trade endpoint includes trade-level charge fields, Ledger exposes debit/credit
running balances, holdings expose delivered/T1 quantities, and Market Quote
can return batched LTP/quote data.

However, current public documentation does **not** establish all of the
following together:

- one authoritative, timestamped trading-account net-liquidation equity
  including cash, all demat/T1 holdings, open derivative positions, collateral,
  MTF/other liabilities and applicable currency conversion;
- a complete intraday external-capital-flow feed, including non-cash asset
  transfers, with an effective time that can be aligned to a live equity
  snapshot (Ledger only documents a voucher date);
- exact session-level semantics for the Positions API's realized/unrealized
  fields and whether these reconcile with Trader's Diary FIFO/speculation P&L;
- a guaranteed complete instrument/asset mapping and usable fresh mark for
  every held asset in an account;
- an authoritative session-open equity observation with restart-safe retrieval.

A computed total could be explored only after the cash/margin/holdings/position
accounting identity is documented and reconciled with real sample statements.
Do not assume `sodLimit + availableBalance`, `availableBalance +
utilizedAmount`, or any combination of collateral/receivables is account
equity. Do not combine position unrealized P&L with position market value or
trade/ledger charges without a written reconciliation equation.

### 7. Implementation gate and test additions

Before implementation can authorize LIVE, the broker-neutral contract and
the Dhan mapping must demonstrate:

- a baseline captured at the actual session boundary and surviving restart;
- two same-account equity observations reconciled to external capital flows;
- deposits/withdrawals and internal transfers do not create artificial P&L;
- trade charges are reflected exactly once;
- full holdings and positions coverage, including carry-forward and T1 state;
- partial close, full close and reversal do not create discontinuous or
  double-counted results;
- corporate actions, share transfers, IPO allotments and product conversions
  are classified as in-scope accounting events or external contributions only
  when source evidence establishes the treatment;
- stale/future marks, missing pages, unmapped instruments, unknown ledger
  classifications, currency mismatch and absent baseline remain UNKNOWN;
- profitable realized P&L with a large current session equity loss is rejected
  by the new limit;
- overnight unrealized loss is not attributed to the current session;
- mark-to-market reversal changes the calculated metric deterministically;
- existing realized-only `max_daily_loss` and `max_drawdown` semantics remain
  unchanged until separately approved;
- no request/account/connection/portfolio mismatch can reach reservation or
  broker submission.

**Current verdict: DESIGN NEEDS MORE EVIDENCE.** The accounting target and the
smallest reusable broker-neutral seam are now specified; Dhan's documented
data cannot yet substantiate complete intraday account equity and capital-flow
alignment. Keep #266 open and preserve #267's fail-closed LIVE boundary. The
next bounded evidence task is to obtain redacted, static Dhan response/statement
fixtures (no credentials) and reconcile the documented field meanings and
cash-equity equation. No broker calls, production assertions, or LIVE changes
are authorized by this design note.
