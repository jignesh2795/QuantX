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


---

## Independent adversarial review reconciliation — 2026-11-03

**Reviewed PR candidate:** `1d1d6f1d76364e18084133fd716f7e227ed79f94`  
**Original PR base:** `6871c46202d4b9256b14d6b5945703c68f0f7de5`  
**Current main reviewed:** `d7d473c39b3cf55b726d69151cd14ce1e51747ed`

The original base is an ancestor of current `main`; 12 commits have landed
since that base. The target planning file is unchanged on current `main`
relative to the original base (same blob SHA
`e8ed5c5793730aad1a3ebd0b51d9a7f8bbd0f44c`). The PR remains a one-file
documentation change; the intervening main commits do not create a conflict
in this file. Source claims below were rechecked against current `main`
rather than assumed from the older PR base.

### Verified persistence and contract facts

- Current `src/quantx/persistence/sqlite/schema.py` declares
  `SCHEMA_VERSION = 8`. Its current schema creates execution lifecycle,
  trading-gate and quarantine tables, market candle/quote tables, and research
  run/result/manifest/experiment tables. It does **not** create account-equity
  observation tables, durable risk-session baseline tables, or an
  external-capital-flow ledger. This absence is verified from the current
  schema declaration and `_create_current_schema` composition, not an
  unverified assumption.
- A durable session-opening baseline therefore cannot be added by simply
  reusing the current schema. Any future persisted baseline requires an
  explicitly designed, versioned SQLite migration (or a separately justified
  persistence backend), plus restart and migration tests. This design note
  does not approve that migration or a schema shape.
- There are two distinct types named `AccountFinancialState`; they must not be
  conflated:
  - `quantx.domain.finance.AccountFinancialState` is the domain risk-context
    value with six required `Money` fields: cash balance, available cash,
    blocked cash, margin used, margin available and buying power. It requires
    one currency and non-negative amounts.
  - `quantx.integrations.reconciliation.account.AccountFinancialState` is the
    broker-neutral observation seam referenced in this design. It carries
    account/connection identity, observation time, source and currency, with
    optional available cash, equity, margin used and margin available. It
    does not currently express an equity basis, trusted capture time,
    complete asset/liability coverage, capital-flow classification or a
    session-opening baseline.
- The reconciliation type is a plausible seam to extend, not an already
  sufficient session-equity contract. Any extension must make the missing
  semantics explicit and must not silently feed a partially observed account
  into LIVE risk.
- PR [#285](https://github.com/jignesh2795/QuantX/pull/285) is merged at
  `6daaa481854fe412bb2582e46d6312c6738d0ba8`. It adds HMAC-bound,
  supplemental **per-position** realized/unrealized P&L observations. It does
  not aggregate them into account/day P&L, derive account equity or a
  high-water mark, populate the corresponding risk snapshot fields, or
  authorize LIVE.
- The proposed formula below uses proposed concepts
  `current_net_liquidation_equity`, `session_open_net_liquidation_equity`
  and `net_external_capital_contributions`. These are design variables,
  **not existing QuantX fields or implemented data sources**. The formula
  remains a proposal until each term has a validated source, scope, currency,
  timestamp and completeness contract.

### Main versus integration-branch Dhan state

This PR targets `main`. At current `main` SHA
`d7d473c39b3cf55b726d69151cd14ce1e51747ed`, the Dhan risk source still
contains the earlier funds mappings that motivated the semantic correction:
`sod_limit` to cash balance, `available_balance` to available cash,
margin available and buying power, `blocked_payout_amount` to blocked cash,
and `utilized_amount` to margin used. The design records these as a semantic
gap; it does not validate or endorse those mappings.

Separately, the integration branch
`integration/quantx-issue267-final-failclosed-repair-2026-11-03` contains
PRs #298 and #299 through merge
`6d21c0998ddedd62f33577928f487e9520e990e4`. There, the Dhan risk-evidence
source advertises no supported LIVE risk fields and returns unavailable
evidence before transport collection. The integration merge does not change
the fact that current `main` has not yet incorporated those slices. Neither
branch establishes Dhan account-level `DAILY_PNL`, complete net-liquidation
equity or LIVE readiness.

### Blocking static-fixture dependencies before implementation

The following redacted, static source fixtures are required to test the
proposed mapping and reconciliation. These are input dependencies, not a
request to make broker calls. Use historical exports or otherwise lawfully
obtained samples; never include credentials, access tokens, real client IDs,
account numbers, names, addresses or other PII.

| Fixture | Minimum content to preserve after redaction | Validation purpose |
|---|---|---|
| `fundlimit.json` | Complete `GET /fundlimit` response, including `sodLimit`, `availableBalance`, `blockedPayoutAmount`, `utilizedAmount`, collateral, receivables and withdrawable balance where present | Establish the actual funds fields and their documented/observed distinctions; do not infer net-liquidation equity |
| `positions.json` | Complete `GET /positions` rows, including security/segment, product and position types, multiplier where present, day and carry-forward quantities/values, realized/unrealized P&L, and response observation time where supplied | Reconcile position-level versus session/account P&L semantics and carry-forward treatment |
| `holdings.json` | Complete `GET /holdings` response with DP, T1, available and collateral quantities and average cost fields | Establish the holdings universe; cost basis is not a current mark |
| `trades_page0.json`, `trades_page1.json` | Consecutive paginated trade-history pages with trade IDs, timestamps, quantities, prices, pagination metadata and all listed charge components | Reconcile trade completeness, realized calculation candidates and charges |
| `ledger.json` | Full session date-range debit/credit entries, voucher dates, narration, voucher references and running balances | Test flow classification and identify what date-only ledger evidence cannot establish |
| `quote_batch.json` | Batched quote response covering every instrument represented in positions and holdings, with quote fields and source timestamps | Test mark coverage and freshness; an incomplete instrument universe must remain UNKNOWN |
| `traders_diary_summary.json` (if obtainable) | The corresponding Trader's Diary realized-P&L summary and adjustments for the same account/session | Cross-check FIFO/closed-position semantics against Positions and Trade History; absence must be recorded, not synthesized |

A redacted fixture set must preserve consistent pseudonymous identities across
files (for example, the same stable alias for one account and broker client),
currency, instrument identifiers needed for cross-file joins, source field
names, timestamps, page ordering, and evidence of whether pagination is
complete. Redaction must not remove the relationships needed to reconcile
trades, positions, holdings, ledger entries and quotes.

The files must represent a coherent account and session. Where the contract
requires a session-opening baseline and a later valuation, samples must include
both relevant observations and enough source history to test capital movements
between them. A single funds or positions response is not evidence of a
complete cash/equity identity. Missing pages, missing instruments, unclassified
ledger rows, date-only timing where intraday attribution is necessary, stale
quotes, or an unavailable Trader's Diary comparison must remain explicit
limitations.

Static fixtures can validate parsing, joins, candidate calculations and
reconciliation hypotheses. They do **not** authenticate the original broker
session, prove that an API guarantees completeness/freshness, establish
production authority, or by themselves authorize any LIVE evidence field.

### Adversarial-review disposition and implementation gate

The independent read-only review dated 2026-11-03 found the accounting design
internally sound and the reviewed Dhan v2 documentation mapping accurate, with
no source-supported basis to weaken the fail-closed conclusion. It identified
the persistence, contract distinction and fixture dependencies made explicit
above.

**Review verdict: PASS WITH FINDINGS — design quality accepted; implementation
not authorized. Current accounting verdict remains DESIGN NEEDS MORE EVIDENCE.**

Implementation remains blocked until the redacted static fixture set is
reconciled, an evidenced account cash/equity identity and capital-flow
classification are established, the session-baseline persistence design is
specified, and the affected migrations and restart behavior are separately
reviewed. Preserve realized-only `daily_pnl`, current `max_drawdown`
semantics and the #267 LIVE fail-closed boundary. No production code, schema,
risk behavior, broker operation or LIVE authorization is changed by this
documentation update.

---

## Issue #266 — session equity P&L accounting contract (2026-11-06)

**Reviewed source baseline:** `main` at `41550505922a294daef4c6aa73fb4c8420b42ab8`.
**Disposition:** accounting semantics defined for subsequent design and implementation planning; source feasibility and implementation remain blocked. This section supersedes the earlier suggestion in Priority 2 to add a bare `unrealized_pnl` value to `RiskSnapshot`. It does not approve a source adapter, persistence migration, risk API change, broker operation or LIVE authorization.

### 1. Contract decisions

1. Preserve `RiskSnapshot.daily_pnl` as **realized-only daily P&L**. Preserve `RiskLimits.max_daily_loss`, its comparison behavior and its existing tests.
2. Preserve the existing `max_drawdown` / `equity` / `high_water_mark` contract unchanged. Session loss and peak-to-trough drawdown are distinct measurements.
3. Define a separate signed metric named **session equity P&L**, represented conceptually as `session_equity_pnl`. The corresponding positive loss threshold is named **`max_session_equity_loss`**. These are design names, not implemented fields or a public API.
4. Use complete, in-scope **net-liquidation equity change adjusted for external capital flows** as the canonical account-level session result. A sum of position rows, a lifetime unrealized P&L value, or an unverified broker daily-P&L figure is not a substitute.
5. Keep realized and unrealized attribution as mutually exclusive explanatory components. Their reconciliation must agree with the equity-derived result; they must not be added to that result a second time.
6. Do not add a standalone current `unrealized_pnl` to `RiskSnapshot` and call it session loss. A current/lifetime unrealized value does not identify the change since this session opened and can import overnight movement or double-count partial closes.
7. The contract is account-risk-scope based. A broker account value is not automatically a strategy-portfolio value. Portfolio-level allocation requires a separate, explicit allocation and evidence contract.

### 2. Definitions, signs and canonical formula

All monetary amounts use exact finite Decimal values and one declared valuation currency.

| Term | Definition |
|---|---|
| `E_open` | Complete net-liquidation equity for the selected account risk scope at the actual session-opening cut |
| `E_t` | Complete net-liquidation equity for the same scope at observation cut `t` |
| `F_ext(s,t]` | Signed net external capital entering the measured scope after the opening cut and through `t`; contribution in is positive, withdrawal/transfer out is negative |
| `session_equity_pnl(t)` | Signed account return attributable to the session, after external-flow neutralization |
| `max_session_equity_loss` | Positive loss threshold in the same valuation currency |

Canonical calculation:

```text
session_equity_pnl(t) = E_t - E_open - F_ext(s,t]
session_equity_loss(t) = max(0, -session_equity_pnl(t))
```

A positive result is a gain; a negative result is a loss. External contributions are positive when entering the measured scope and negative when leaving it. Therefore a deposit or asset transfer in does not create trading profit, and a withdrawal or asset transfer out does not create trading loss. A transfer wholly inside the measured scope is neutral.

If later implemented, the new limit rejects when `session_equity_loss > max_session_equity_loss`, using a finite positive Money threshold in the same currency. Equality is not an exceeded limit, consistent with the current strict-greater-than daily-loss comparison. This definition does not change or alias `max_daily_loss`.

### 3. Account risk scope and net-liquidation equity

The measured scope is identified by the canonical account ID, broker-connection ID, explicit risk-scope ID, valuation currency, session/calendar identity and versioned accounting policy. Every asset, liability, flow, trade and mark must belong to that same scope. Do not silently use account equity for a strategy portfolio or combine two accounts because they share a client login.

```text
net_liquidation_equity
    = sum(complete, non-duplicated asset values)
    - sum(complete, non-duplicated liability values)
```

The asset/liability inventory must explicitly cover, where applicable:

- settled and unsettled cash, with debit/credit and settlement state distinguished;
- all open positions, including carry-forward and intraday quantities;
- demat, delivered, T1 and other in-scope holdings;
- collateral assets and receivables, only under a documented recognition and valuation basis;
- MTF borrowing, financing, margin/debit liabilities, accrued interest, borrow costs, taxes, charges and other obligations;
- unsettled trade payables/receivables and other account obligations;
- every required currency conversion under a named, timestamped FX source and policy.

Count each economic asset or liability exactly once. Pledged securities remain the same asset; a collateral label does not create a second asset. Cash, collateral, receivables and broker fund-limit fields must not be added together unless their source semantics prove they are disjoint. Holdings and position rows must be reconciled to avoid counting the same instrument quantity twice. Derivatives require the correct instrument-specific valuation and settlement basis, contract multiplier and currency; notional exposure is not automatically an asset value.

The valuation basis is net liquidation value, not available cash, buying power, margin limit, gross exposure, average cost or start-of-day funds limit. Each asset class and venue requires an explicit mark-selection rule appropriate to its liquidation side, quote type, size/depth assumptions, contract/settlement conventions and freshness bound. Missing/unmapped assets, unsupported liabilities, absent marks, stale marks, unknown FX, or an unverified equity basis make the entire required equity observation unavailable. A partial aggregate must never be promoted to complete.

### 4. Session boundary, observation time and baseline

The session is defined by an explicit market calendar and policy, not by civil midnight. For the initial India implementation, use an explicit Asia/Kolkata exchange-session identity, including holidays, special sessions and the selected exchange/segment. An account spanning markets with different session calendars must use a deliberate composite-session policy or be partitioned into separately measured scopes; do not assume one universal opening instant.

Each relevant observation retains at least:

- source/provider `observed_at` (the instant the source says the value represents);
- trusted host `captured_at` (when QuantX received it);
- effective/event time where a trade, charge or capital flow occurred;
- account, connection, scope, currency and source identity;
- source record references/fingerprint and pagination/cursor or snapshot identity.

A recent local capture does not make an old source value current. Components must represent a coherent observation cut or have a documented bounded alignment policy. The baseline must represent the actual session opening; the first observation obtained after trading has begun is not a substitute. If a provider can supply a historical/as-of opening cut, its semantics and completeness must be verified. Otherwise the baseline is unavailable.

The durable baseline is write-once per key: account, connection, risk scope, calendar/session ID, valuation currency and accounting-policy version. It retains the baseline equity, source observation/cut identity, source observation time, trusted capture time and provenance. Repeated identical capture is idempotent; a conflicting baseline is an integrity failure. Restart must reload the same baseline, never silently reset it. Starting after the session boundary without recoverable opening evidence means UNKNOWN/unavailable.

Current SQLite schema v8 has no account-equity observation, external-capital-flow or session-baseline persistence contract. No schema shape or migration is approved by this document. A separate persistence design, migration review, rollback/restart tests and repository boundary are prerequisites.

### 5. Realized, unrealized and other component attribution

The equity-derived formula is canonical. A component ledger is used to explain and reconcile it, not to replace it with partial aggregates:

```text
component_session_result
    = realized_session_trading_pnl
    + unrealized_session_mtm_change
    + recognized_distributions_and_other_income
    + documented_non-capital_accounting_adjustments
    - transaction_charges
    - financing_and_borrow_costs
    - other_recognized_expenses
```

The component result must reconcile to `session_equity_pnl` after the same external-flow treatment. Every component declares whether it is gross or net and whether costs are already embedded. A fee, tax or charge reflected in net execution proceeds, cash/equity or another component must not be subtracted again. No unexplained balancing residual is permitted. Reconciliation outside a documented source-precision bound makes the result unavailable; no tolerance may be invented to make a sample pass.

**Realized session trading P&L** is the session movement recognized on quantities closed during the session, not lifetime realized P&L or an undocumented broker row total. For a carried position, the session-opening mark/settlement is the basis for the quantity closed during this session; prior-session gains/losses are not re-attributed to today. For a position opened intraday, execution price is its opening basis. Use an explicit, versioned market/product lot-matching and settlement policy; do not assume one universal FIFO or average-cost rule.

**Unrealized session MTM change** is the mark movement on quantities still open at observation cut `t`, relative to their session-opening mark for carried inventory or execution basis for intraday-opened inventory. Use signed quantity and the correct contract multiplier/settlement semantics. Recompute against the same fixed baseline on each observation; never accumulate successive snapshots. The current lifetime unrealized P&L of a carried position is not the session change.

For partial closes, allocate the closed quantity to realized session P&L using the same opening basis and retain only the remaining quantity in unrealized MTM. For a full close, retain the realized session result even though the position no longer appears in the current open-position response. For a reversal, split the fill into closing the old side and opening the new side, each with its correct basis. Missing trade events, ambiguous lot allocation or incomplete closed-position coverage makes the component reconciliation unavailable.

**Other items:** recognized dividends/distributions/interest are recorded as income at the documented entitlement/effective basis, not as external contributions. Splits, bonuses, mergers, product conversions, expiry/settlement, exercise/assignment and IPO allotments are explicit accounting events with source identity and quantity/basis transformations. They are not automatically external capital flows. Cash-in-lieu, withholding and other associated amounts are recognized once. If the event cannot be classified and reconciled, the result is unavailable.

### 6. External capital flows and charges

A capital flow is external only relative to the chosen measured scope:

- cash or securities entering the scope: positive signed contribution;
- cash or securities leaving the scope: negative signed contribution;
- transfer between accounts wholly inside the measured scope: zero net flow;
- transfer to/from an account outside the scope: external flow, valued at its effective instant.

Non-cash transfers require canonical asset identity, quantity, valuation currency, effective time and an evidenced transfer-time valuation. A voucher date without intraday timing is insufficient when the flow must be aligned to an intraday equity cut. Unknown flow classification or missing pages makes `F_ext` incomplete.

Brokerage, exchange charges, taxes, stamp duty, financing, MTF interest, borrow costs and other expenses are trading/account expenses, not capital contributions. Recognize each exactly once at the policy-defined effective/accrual time. If the selected equity snapshot already includes an expense, the component ledger marks it included; it must not be deducted again. If a required expense is accrued but absent from the equity/source view and cannot be measured, the session result is unavailable.

Corporate actions are not automatically flows. Splits/bonuses normally transform quantity and reference basis; dividends and distributions are income; cash-in-lieu and settlements are explicit realized/adjustment events. IPO allotments, share transfers, mergers and product conversions require event-level classification based on whether value crossed the measured account boundary. Never classify by narration text alone or infer economic meaning from a label.

### 7. Temporal, price and numeric integrity

- Every held/position instrument must map to a canonical instrument and applicable market/product rule version.
- Marks require source identity, source observation time, selected time, price type and the segment-specific selection/freshness policy. A stale last trade, missing quote, absent quote size where required, or non-tradable price basis is unavailable.
- The same observation cut must include positions, holdings, cash, liabilities, trades, charges, flows and marks. Complete pagination and stable snapshot/cursor boundaries must be proven. Missing or duplicated pages, repeated trade/flow identities, unmapped rows or contradictory totals fail closed.
- Cross-currency equity requires fresh, source-identified FX observations and an explicit conversion policy at the relevant times. Otherwise the account is not completely valued in the selected currency.
- Parse and calculate with exact finite Decimal values. Source precision loss, float-origin values, rounding, contract multipliers and currency minor-unit treatment require explicit bounds and policy. `Decimal(str(parsed_float))` does not recover precision already lost upstream.
- Provider timestamps and local capture times are never interchangeable. Future-dated observations, inconsistent windows and stale marks make the metric unavailable.

### 8. High-water mark and drawdown remain separate

The existing `RiskSnapshot.equity`, `high_water_mark` and `max_drawdown` behavior is unchanged by #266. Session equity P&L compares this session's opening equity with current equity after neutralizing external flows; drawdown measures decline from a peak over a separately configured horizon.

For a future flow-adjusted account HWM, the preferred design is a unitized/flow-neutralized equity series: external contributions issue units and withdrawals redeem units at the pre-flow unit value, so a deposit or withdrawal alone does not create a new performance peak or drawdown. The HWM is the maximum observed unit value over the configured horizon. Its sampling cadence and the possibility of an unsampled intraperiod peak must be reported. This requires complete, timestamped flow and equity evidence and durable restart-safe state. It is a separate future contract; it must not be smuggled into #266's session metric or used to reinterpret the current raw `max_drawdown` inputs.

### 9. Enforcement and mode boundaries

A pre-trade session-equity loss check can only block a new dispatch when a complete, fresh and authoritative session result is available at that evaluation cut. It is not a continuous MTM monitor, does not retroactively cancel an accepted order and does not liquidate or flatten an existing position. Continuous monitoring, durable mid-session gate trips, reduce-only/flatten capability and lifecycle/recovery behavior require separate designs and authorization.

The economic definitions should be mode-neutral across backtest, paper, sandbox and LIVE. The evidence provenance is not interchangeable: simulation modes use deterministic, explicitly model/version-tagged fills and marks; LIVE requires application-owned, account/connection/request-bound broker evidence. Simulated or caller-supplied observations can validate accounting logic but cannot authorize LIVE. Keep the existing single accounting path (`FillAccounting`, `CashLedger`, valuation and account-state building blocks); do not create a parallel P&L engine. A policy consumer must explicitly state whether it evaluates pre-trade, post-trade or projected state; those evaluation moments are not interchangeable.

### 10. Required test acceptance matrix for a later implementation

| Area | Required deterministic acceptance evidence |
|---|---|
| Formula/signs | Gain, loss, deposit, withdrawal, securities transfer in/out, internal transfer and zero-flow cases; exact Decimal arithmetic and currency rejection |
| Threshold | Positive Money threshold; below/equal/above boundary; disabled policy leaves existing behavior unchanged |
| Legacy contracts | Existing realized-only `daily_pnl` / `max_daily_loss` tests unchanged; existing `max_drawdown` tests unchanged |
| Attribution | Profitable realized result with larger negative session MTM; carry-forward basis; intraday open/close; partial close; full close absent from open book; reversal; repeat snapshot recomputation |
| Costs/income | Fees, taxes, brokerage, financing and charges included once; dividends/distributions and withholding; no charge duplication between trade, ledger and equity |
| Corporate actions | Split/bonus, merger/conversion, expiry/settlement, exercise/assignment and cash-in-lieu; unknown event remains unavailable |
| Scope/coverage | Account/connection/scope mismatch; complete holdings + positions; collateral counted once; MTF/liabilities and unsettled obligations; missing/unmapped asset |
| Marks/time | Stale, future, missing and inconsistent marks; session holiday/special session; source time vs capture time; mixed-calendar policy; FX missing/stale |
| Completeness | Missing/duplicate trade or ledger page; unstable cursor; incomplete flow history; duplicate event IDs; contradictory balances; unexplained component residual |
| Baseline/persistence | True session-open baseline; late start without baseline; duplicate identical baseline; conflicting baseline; restart reload; migration rollback/failure |
| Safety boundary | Missing/UNKNOWN evidence rejects before reservation and submit; no automatic retry, flatten or broker call |
| Mode provenance | Same economic result from equivalent deterministic simulation inputs; simulation evidence cannot satisfy LIVE source authority |

### 11. Implementation prerequisites and current evidence disposition

The accounting contract does not make the source problem feasible. Before any account/session metric can be implemented for LIVE, require:

1. A coherent, lawfully obtained, redacted fixture set preserving source fields, timestamps, page continuity, pseudonymous identity and cross-file joins. The 2026-11-03 issue comment reported 0 of 7 required fixtures; verify the present local inventory before relying on that historical report.
2. A source-backed account-equity identity covering every in-scope asset and liability, with no double counting and an explicitly supported valuation currency.
3. Complete and timestamped cash and non-cash external-flow history, including effective times and classifications.
4. Complete trade/closed-position history, lot/settlement semantics, charge attribution and complete marks for the full instrument universe.
5. An authoritative session-opening baseline and a coherent current observation cut.
6. A separately reviewed durable repository/schema migration and restart/rollback contract for baselines (and, later, HWM state).
7. End-to-end evidence authority and request/account/connection/scope binding under #267, with regression proof that every unavailable or contradictory value blocks before reservation and submission.

The recent #267 feasibility audit reports that the current Dhan adapter cannot legitimately supply any of its 12 required LIVE risk-evidence fields; `_SUPPORTED_FIELDS` must remain empty. That result is consistent with this #266 contract: the #267 field list is not a substitute for session-accounting inputs, and no Dhan funds, position, trade-history or ledger field may be relabelled as complete account equity or session P&L. A different broker/source may be evaluated only against this full contract; do not assume feasibility.

**Current disposition: ACCOUNTING SEMANTICS DEFINED; SOURCE FEASIBILITY NOT ESTABLISHED; IMPLEMENTATION NOT AUTHORIZED.** Keep #266 open. Keep #267 open, Dhan LIVE fields unsupported and the sanctioned LIVE path blocked. No source, tests, schema, migration, broker adapter, issue state or LIVE behavior is changed by this design addendum.
