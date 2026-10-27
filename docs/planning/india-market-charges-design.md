# QX-12 / #200 — India Market Charges: Source Inventory and Design

**Branch:** `local-docs-work`  **HEAD:** `05be62743e7b80ef9681e78fbb0077a659b7c55b`
**Phase:** research + design only. No production source code changed. No roadmap/STATUS touched.
**Scope:** effective-dated Indian equity delivery, intraday, futures, and options transaction charges.
**Related (tracked separately, not reopened):** #267 risk-evidence authority, #266 daily-loss semantics, #196/#197.

---

## 1. Source inventory

All rates below are taken from primary or exchange-published sources. Secondary
broker blogs are used only for cross-checks and are never treated as
authoritative. Every row records the source URL and the publication/effective
date actually stated by that source.

| # | Source (primary unless noted) | URL | Date stated | Covers |
|---|---|---|---|---|
| S1 | NSE — "SEBI Turnover Fees, STT and Other levies" | https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies | current page (no single effective date; STT column states "w.e.f. April 1, 2026" vs "upto March 31, 2026") | STT table, stamp duty table, SEBI turnover fee, GST rate on broker services |
| S2 | NSE — "Securities Transaction Tax" (computation) | https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax | current page | STT computation basis (premium for options, traded price for futures, intrinsic value on exercise) |
| S3 | NSE circular FATAX73524 | https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf | dated March 31, 2026; effective April 1, 2026 | STT revision: futures 0.02→0.05%, options sell 0.10→0.15%, options exercised 0.125→0.15% |
| S4 | NSE circular FA64232 | https://nsearchives.nseindia.com/content/circulars/FA64232.pdf | dated September 27, 2024; effective October 1, 2024 | Uniform (non-slab) exchange transaction charges: cash Rs 2.97/lakh, futures Rs 1.73/lakh, options Rs 35.03/lakh each side |
| S5 | NSE circular FA73061 | https://nsearchives.nseindia.com/content/circulars/FA73061.pdf | dated February 27, 2026; effective March 1, 2026 | Revised exchange transaction charges + IPFT: cash Rs 306.99+0.01, futures Rs 182.99+0.01, options Rs 3552.99+0.01 per crore each side |
| S6 | IBKR India fee schedule (cross-check only) | https://brokerage.ibkr.com/en/accounts/fees/indiaStockExchangeFees.php | current | Cross-checks NSE charges, STT, stamp duty, SEBI fee, IPFT, GST applicability |
| S7 | SEBI bulletin (historical STT) | https://www.sebi.gov.in/sebi_data/attachdocs/1334565322526.pdf | historical | Older STT rates (cash delivery 0.125% at that time); confirms Finance Act 2004 basis |

Secondary/derived (not authoritative, used only for cross-checks): broker blogs
(stolo.in, choiceindia.com, smctradeonline.com, fyers.in). These are never the
sole basis for a verified rate.

---

## 2. Verified rates

All rates are percentages of the stated basis. "Buyer/Seller" is the liable party.
Effective dates are those stated by the cited source. Where a source does not
state an effective date, it is marked UNRESOLVED rather than invented.

### 2.1 Securities Transaction Tax (STT) — source S1, S2, S3

Basis: premium for options; traded price for futures; volume-weighted average
price for equity delivery; intrinsic value on exercise.

| Product | Side | Rate (current, w.e.f. Apr 1, 2026) | Rate (upto Mar 31, 2026) | Liable party | Basis |
|---|---|---|---|---|---|
| Equity delivery | Buy | 0.100% | 0.100% | Purchaser | transaction value (VWAP) |
| Equity delivery | Sell | 0.100% | 0.100% | Seller | transaction value (VWAP) |
| Equity intraday (non-delivery) | Sell | 0.025% | 0.025% | Seller | transaction value |
| Equity-oriented fund unit delivery | Buy | NIL | NIL | — | — |
| Equity-oriented fund unit delivery | Sell | 0.001% | 0.001% | Seller | transaction value |
| Equity futures | Sell | 0.05% | 0.02% | Seller | traded price |
| Equity options | Sell (premium) | 0.15% | 0.10% | Seller | premium |
| Equity options | Exercise | 0.15% | 0.125% | Purchaser | intrinsic value (settlement price − strike) × qty |
| Equity options | Buy | 0% (no STT) | 0% | — | — |

Verified: S1 (table), S3 (circular). The prior-regime effective date (when
0.02%/0.10%/0.125% began) is NOT stated in S1/S3 — see §4 (UNRESOLVED).

### 2.2 Stamp duty — source S1 (Indian Stamp Act, collected by states)

| Product | Rate | Liable party |
|---|---|---|
| Equity delivery (transfer) | 0.015% | Buyer |
| Equity intraday (non-delivery) | 0.003% | Buyer |
| Equity futures | 0.002% | Buyer |
| Equity options | 0.003% | Buyer |
| Currency / IR derivatives | 0.0001% | Buyer |
| Debentures | 0.0001% | Buyer |
| Commodity futures | 0.002% | Buyer |
| Government securities | 0% | — |
| OFS / takeover / buyback / delisting (delivery) | 0.015% | Seller (offeror) |

Verified: S1 table. Effective date of these uniform rates is stated in S1 only
as the current published schedule; the underlying Indian Stamp Act amendment
effective date (commonly cited as July 1, 2020) is not re-verified here —
see §4.

### 2.3 SEBI turnover fee — source S1

| Segment | Rate | Liable party |
|---|---|---|
| Non-debt securities (equity, derivatives) | 0.0001% (Rs 10 per crore) | both buy and sell |
| Debt securities | 0.000025% (Rs 2.5 per crore) | both buy and sell |

Verified: S1. Effective date of the current Rs 10/crore rate is not stated in
S1 — see §4 (UNRESOLVED).

### 2.4 Exchange transaction charges (NSE) — sources S4, S5

Per crore of traded value, each side (buy and sell), unless noted.

| Segment | Basis | Rate (w.e.f. Mar 1, 2026) | Rate (Oct 1, 2024 – Feb 28, 2026) | Rate (before Oct 1, 2024) |
|---|---|---|---|---|
| Cash (equity) | traded value | Rs 307.00 (306.99 + 0.01 IPFT) | Rs 307.00 (297 + 10 IPFT) | slab-wise, volume-dependent |
| Equity futures | traded value | Rs 183.00 (182.99 + 0.01) | Rs 183.00 (173 + 10) | slab-wise, volume-dependent |
| Equity options | premium value | Rs 3,553.00 (3,552.99 + 0.01) | Rs 3,553.00 (3,503 + 50) | slab-wise, volume-dependent |

Verified: S4 (Oct 1, 2024 uniform rates), S5 (Mar 1, 2026 revised split).
The pre-Oct-1-2024 slab-wise structure is not representable as a single rate —
see §4 (UNRESOLVED / out of scope for a single-rate schedule).

Note: IPFT contribution is included in the totals above; it is NOT added again
as a separate component.

### 2.5 GST — source S1 (GST rate), S6 (applicability)

| Component | GST rate | Applicability |
|---|---|---|
| Brokerage | 18% | broker-specific (not in universal schedule) |
| Exchange transaction charges | 18% | yes |
| SEBI turnover fee | 18% | yes (per S6, "from April 2025") |
| IPFT contribution | 18% | treated as part of exchange charge (S6 confirms GST on exchange charges) |
| STT | exempt | no |
| Stamp duty | exempt | no |
| DP charges | 18% | broker/DP-specific |

Verified: S1 states "Stock brokers Services 18.00% (GST)"; S6 confirms GST
applies to exchange transaction charges and SEBI fees, not STT/stamp duty.
GST is a statutory tax rate under GST law; the 18% rate and its effective
date are governed by GST Council notifications (primary statute citation not
re-verified here — see §4).

### 2.6 Brokerage and DP charges — NOT universal

Brokerage is not regulated by SEBI (caps removed in 2003) and varies by
broker/plan. DP (depository participant) charges vary by DP/broker. These are
out of scope for a universal schedule and must remain caller-supplied
configuration, not embedded in the India schedule.

---

## 3. Identified gaps in current implementation

1. `execution/charges.py` provides only `PercentageBpsChargeModel` — a single
   configured percentage. No effective date, no side/product awareness, no
   multi-component breakdown for Indian statutory charges.
2. No India-specific charge module exists under `india/`.
3. `ChargeCalculationContext` carries only `transaction_value` and `currency`;
   it lacks trade side, product, effective date, exercise flag, premium basis.
4. No effective-dated schedule selection mechanism for charges (the venue-rule
   snapshot pattern in `india/rule_data.py` is the reusable template).
5. No charge-specific golden tests for statutory Indian charges.
6. Paper/research execution uses `fee_bps` → `PercentageBpsChargeModel`; Indian
   statutory charges are not applied anywhere today.

---

## 4. Unresolved / unsupported cases (do not guess)

| Item | Status | Reason |
|---|---|---|
| STT prior-regime effective date (when 0.02%/0.10%/0.125% began) | UNRESOLVED | S1/S3 only state "upto March 31, 2026" for the prior column; no start date given. Do not invent one. |
| SEBI turnover fee effective date (current Rs 10/crore) | UNRESOLVED | S1 states the rate but no effective date. |
| Stamp duty effective date (uniform rates) | UNRESOLVED (partial) | S1 states rates; underlying Indian Stamp Act amendment date (commonly July 1, 2020) not re-verified against the primary statute in this phase. |
| GST 18% effective date for these services | UNRESOLVED (partial) | GST rate from GST law; primary notification citation not re-verified here. |
| Exchange charges before Oct 1, 2024 | UNSUPPORTED (slab-wise) | Volume-dependent slabs; cannot be represented as a single rate. Fail closed for dates before Oct 1, 2024. |
| Brokerage rates | OUT OF SCOPE | Broker-specific, not regulated. |
| DP charges | OUT OF SCOPE | DP/broker-specific. |
| Currency/commodity derivatives charges | PARTIAL | Stamp duty rates listed (S1); exchange transaction charges for currency/commodity not in S4/S5 (only equity cash/futures/options covered). Mark unsupported until primary source added. |
| Options exercise intrinsic value computation | NEEDS INPUT | Requires settlement price and strike; charge model must receive these as inputs (fail closed if missing). |
| BSE-specific charges | NOT RESEARCHED | This phase covers NSE only. BSE has its own transaction charge schedule (different rates). Add as a separate scope when needed. |
| MCX/NCDEX commodity charges | NOT RESEARCHED | Out of scope for this phase. |

---

## 5. Proposed contract (design only — not implemented)

### 5.1 New module: `src/quantx/india/charges.py`

Reuse existing infrastructure; do not modify `execution/charges.py` universal core
beyond what is strictly necessary (proposed: no changes to charges.py at all).

Components:

1. **`IndiaTradeSide`** enum: `BUY`, `SELL`.
2. **`IndiaChargeProduct`** enum: `DELIVERY`, `INTRADAY`, `FUTURES`, `OPTIONS`.
3. **`IndiaChargeCalculationContext`** dataclass extending `ChargeCalculationContext`:
   - `trade_side: IndiaTradeSide`
   - `product: IndiaChargeProduct`
   - `effective_at: datetime` (tz-aware; fail closed if naive)
   - `is_exercise: bool = False`
   - `premium_value: Decimal | None = None` (options premium basis; defaults to transaction_value)
   - `exercise_value: Decimal | None = None` (intrinsic value basis; required when is_exercise)
   - `brokerage: Decimal | None = None` (for GST base; None = exclude brokerage from GST)
4. **`IndiaChargeRateSet`** frozen dataclass: Decimal | None fields per component
   (stt_rate, stamp_duty_rate, exchange_txn_rate, ipft_rate, sebi_turnover_rate,
   gst_rate). `None` = not applicable for that (product, side) combination → the
   model raises `IndiaChargeRuleUnavailable` (fail closed). `0` is a valid rate.
5. **`IndiaChargeScheduleEntry`** frozen dataclass: `effective_from`, `effective_to`
   (None = current), `version`, `source_ref` (URL/circular), `rates`
   (Mapping[(IndiaChargeProduct, IndiaTradeSide), IndiaChargeRateSet]).
6. **`IndiaChargeSchedule`** frozen dataclass: tuple of entries (sorted by
   effective_from), with `select(effective_at) -> IndiaChargeScheduleEntry`
   (raises `IndiaChargeRuleUnavailable` if no entry covers the date).
7. **`IndiaMarketChargeModel`** implementing `ChargeModel`:
   - `model_id = "india.market_charges"`
   - `model_version = schedule.version` (selected entry's version)
   - `calculate(context)`:
     - require `IndiaChargeCalculationContext`; else raise TypeError.
     - validate tz-aware effective_at.
     - select schedule entry; if none → raise `IndiaChargeRuleUnavailable`.
     - look up rate set for (product, side); if None → raise.
     - compute each component with exact Decimal arithmetic:
       - stt = basis × stt_rate (basis = transaction_value, or premium_value for
         options sell, or exercise_value for exercised options)
       - stamp_duty = transaction_value × stamp_duty_rate
       - exchange_txn = transaction_value × exchange_txn_rate
       - ipft = transaction_value × ipft_rate
       - sebi = transaction_value × sebi_turnover_rate
       - gst_base = exchange_txn + ipft + sebi + (brokerage if provided)
       - gst = gst_base × gst_rate
     - return `ChargeBreakdown` with components (stt, stamp_duty, exchange_txn,
       ipft, sebi_turnover_fee, gst) and provenance =
       (source_ref, f"effective:{entry.effective_from.isoformat()}", f"version:{version}").
   - Raise `IndiaChargeRuleUnavailable` for any missing/unsupported scope.

8. **`IndiaChargeRuleUnavailable`** exception (subclass of ValueError) — stable
   error code string carried in the message, e.g.
   `INDIA_CHARGE_RULE_UNAVAILABLE: no schedule entry for 2023-01-01`.

### 5.2 Date selection

- `effective_at` is tz-aware (Asia/Kolkata or UTC; the model normalizes to
  comparison against entry effective dates, which are stored tz-aware).
- Select the single entry where `effective_from <= effective_at` and
  (`effective_to is None` or `effective_at < effective_to`).
- If two entries overlap → construction-time validation rejects (entries must
  be contiguous, non-overlapping).
- If no entry covers the date → `IndiaChargeRuleUnavailable` (fail closed).

### 5.3 Provenance

- Each schedule entry carries `source_ref` (URL or circular reference like
  "NSE circular FA73061").
- `ChargeBreakdown.provenance` = (source_ref, effective date, version).
- The model never synthesizes a rate; it only applies supplied rates.

### 5.4 Decimal / fail-closed

- All rates and amounts are Decimal. Non-Decimal inputs raise TypeError
  (matching charges.py convention).
- Negative rates raise ValueError.
- Missing schedule / unsupported (product, side) / naive timestamp → raise
  `IndiaChargeRuleUnavailable` or ValueError. Never return a zero or partial
  breakdown for an unsupported case.
- `None` rate = unsupported → raise. `0` = valid zero charge.

### 5.5 What stays in the universal core

`execution/charges.py` is NOT modified. The India module imports `ChargeModel`,
`ChargeBreakdown`, `ChargeComponent`, `ChargeCalculationContext` from it and
adds India-specific logic on top. This preserves the "no Indian tariffs in the
universal core" boundary (ADR-010, doc 52).

---

## 6. Implementation sequence

1. **This document** (research + design) — done.
2. Create `src/quantx/india/charges.py` with the contract above. No hardcoded
   rates; rates are caller-supplied data.
3. Add unit tests `tests/unit/india/test_market_charges.py` with golden
   calculations using verified rates from §2 as test fixtures (test data, not
   production code).
4. (Separate slice) Add a versioned data file (e.g.
   `src/quantx/india/data/market_charges_schedule.py` or JSON) populated with
   verified rates + effective dates + source_refs. Wire a loader that builds an
   `IndiaChargeSchedule`. This slice requires its own source-evidence review.
5. (Separate slice) Wire into paper execution when a charge model is selected;
   keep `PercentageBpsChargeModel` as the default fallback for non-India or
   unverified dates.
6. Update docs (52-transaction-cost-and-charges.md, india skill) only after
   implementation is accepted and verified.

Do not bundle steps 2–6 into one change. Each is a separate, reviewable slice.

---

## 7. Acceptance matrix (golden tests)

| # | Test | Expected |
|---|---|---|
| T1 | Equity delivery buy, Rs 10,000, on/after Apr 1 2026 | STT 0.1% (buyer), stamp 0.015% (buyer), exchange 0.0030699%, IPFT 0.0000001%, SEBI 0.0001%, GST 18% on (exchange+IPFT+SEBI) |
| T2 | Same trade on Mar 15, 2026 (before Apr 1 2026 STT unchanged for delivery; exchange rate still Rs 307) | STT 0.1%, exchange Rs 307/crore |
| T3 | Equity intraday sell, Rs 10,000, any date in supported range | STT 0.025% (seller), stamp 0.003% (buyer), exchange+SEBI+GST |
| T4 | Equity futures sell, Rs 1,00,000, on/after Apr 1 2026 | STT 0.05% (seller) on traded price; stamp 0.002%; exchange Rs 183/crore |
| T5 | Same futures trade on Feb 15, 2026 | STT 0.02% (seller); exchange Rs 183/crore (Mar 1 2026 rate NOT yet in effect → use Oct 1 2024 rate Rs 183? Wait: Feb 15 2026 is between Oct 1 2024 and Mar 1 2026, so exchange rate = Rs 183/crore (173+10). STT = 0.02% (prior regime).) |
| T6 | Equity options sell (premium Rs 5,000), on/after Apr 1 2026 | STT 0.15% on premium (seller); stamp 0.003%; exchange Rs 3,553/crore on premium |
| T7 | Equity options sell, before Apr 1 2026 | STT 0.10% (seller); exchange Rs 3,553/crore (if on/after Mar 1 2026) or Rs 3,553/crore (Oct 2024 rate) |
| T8 | Equity options exercise, on/after Apr 1 2026 | STT 0.15% on intrinsic value (purchaser); missing exercise_value → fail closed |
| T9 | Trade on Feb 1, 2024 (before Oct 1, 2024) | `IndiaChargeRuleUnavailable` (slab-wise, unsupported) |
| T10 | Unsupported product (e.g. currency futures) | `IndiaChargeRuleUnavailable` |
| T11 | Unsupported side for a product (e.g. STT on buy intraday = 0, but exchange still applies; verify 0 is valid, not None) | charge computed with STT 0 |
| T12 | Missing provenance (schedule entry with empty source_ref) | construction raises ValueError |
| T13 | Naive (non-tz-aware) effective_at | ValueError / fail closed |
| T14 | Non-Decimal rate or amount | TypeError |
| T15 | Negative rate | ValueError |
| T16 | GST base includes brokerage when provided; excludes when None | two cases, exact Decimal |
| T17 | Trade exactly on boundary date (e.g. Apr 1 2026 00:00 IST) | uses new rate (effective_from inclusive) |
| T18 | Trade one second before boundary (Mar 31 2026 23:59:59 IST) | uses prior rate |
| T19 | `ChargeBreakdown.total` equals sum of components (exact Decimal) | assert |
| T20 | Provenance tuple contains source_ref, effective date, version | assert |

Note: T5/T7 date/rate interactions are intentionally complex to exercise the
effective-date selection logic. Test fixtures must use verified rates only.

---

## 8. Out of scope (do not implement in this slice)

- New accounting engine or replacing `execution/charges.py`.
- Hardcoding unverified rates in production code.
- Brokerage, DP charges (broker-specific).
- BSE/MCX/NCDEX charge schedules.
- Currency/commodity derivatives (until primary source added).
- SEBI compliance layer (ADR-010).
- LIVE broker receipt charges (separate slice, needs authoritative broker evidence).
- #267 (risk-evidence authority) and #266 (daily-loss semantics) — tracked separately.

---

## 9. Unresolved questions

1. Should GST be computed by the charge model or by the accounting layer? (Proposed: by the charge model, since it depends on the charge components; but brokerage GST is the caller's responsibility. Confirm with accounting owner.)
2. Should the schedule be loaded from a Python data module or a versioned JSON/YAML file? (Proposed: Python data module with frozen dataclasses, consistent with `india/rule_data.py`.)
3. Should IPFT be a separate component or folded into exchange transaction charge? (Proposed: separate, for auditability — but it is billed as part of the NSE transaction charge total. Decide before implementation.)
4. BSE support: add as a separate scope or parameterize the schedule by exchange? (Proposed: separate scope; NSE first.)
5. Pre-Oct-1-2024 slab-wise charges: should we support a volume-tiered schedule entry, or permanently fail closed for those dates? (Proposed: fail closed; volume tiers add complexity and are rarely needed for research.)

---

## 10. Evidence status

- **Structural inspection:** `execution/charges.py`, `india/execution_rules.py`,
  `india/rule_data.py`, `india/domain.py`, `research/provenance.py`,
  `research/point_in_time.py`, `tests/unit/execution/test_charges.py`,
  `docs/architecture/52-transaction-cost-and-charges.md` — all read.
- **Runtime/test/CI evidence:** none collected in this phase. No tests run,
  no code changed. The only checks run were repository-integrity checks on
  the skill library (unrelated to this task).
- **Source research:** web search + primary source extraction (S1–S7 above).
  Rates marked UNRESOLVED are not verified and must not be used in
  implementation until resolved.
