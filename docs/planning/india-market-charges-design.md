# QX-12 / #200 — India Market Charges: Source Inventory and Design

**Branch:** `local-docs-work`
**Phase:** research + design only. No production source code changed. No roadmap/STATUS touched. Git records the commit SHA; this document does not self-assert its own HEAD.
**Scope:** effective-dated Indian equity delivery, intraday, futures, and options transaction charges.
**Related (tracked separately, not reopened):** #267 risk-evidence authority, #266 daily-loss semantics, #196/#197.

---

## 1. Source inventory

Sources are split into **primary authorities** (exchange circulars, applicable
legislation, and regulatory circulars that originate the rate) and **secondary
cross-checks** (broker/exchange-published info pages and third-party brokers).
A secondary source may corroborate a rate but never establishes an effective
date or supersedes a primary circular. Where a historical effective date is not
stated by a primary circular or the governing law, it remains UNRESOLVED
rather than being filled in from a secondary page.

### 1.1 Primary authorities

| # | Source | URL | Date stated | Covers |
|---|---|---|---|---|
| P1 | NSE circular FATAX63809 (STT, Finance Act 2024) | https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf | dated September 9, 2024; effective October 1, 2024 | STT: options sell 0.0625→0.10%, futures 0.0125→0.02%; prior rates upto September 30, 2024 |
| P2 | NSE circular FATAX73524 (STT, Finance Act 2026) | https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf | dated March 31, 2026; effective April 1, 2026 | STT: options sell 0.10→0.15%, options exercised 0.125→0.15%, futures 0.02→0.05% |
| P3 | NSE circular FA64232 (transaction charges, SEBI circular SEBI/HO/MRD/TPD-1/P/CIR/2024/92) | https://nsearchives.nseindia.com/content/circulars/FA64232.pdf | dated September 27, 2024; effective October 1, 2024 | Uniform (non-slab) exchange transaction charges: cash Rs 2.97/lakh, futures Rs 1.73/lakh, options Rs 35.03/lakh each side |
| P4 | NSE circular FA73061 (transaction charges + IPFT split) | https://nsearchives.nseindia.com/content/circulars/FA73061.pdf | dated February 27, 2026; effective March 1, 2026 | Revised split: cash Rs 306.99+0.01, futures Rs 182.99+0.01, options Rs 3552.99+0.01 per crore each side; total member outflow unchanged |
| P5 | Indian Stamp Act 1899 as amended (uniform stamp duty) | primary statute; NSE page documents the table | amendment effective July 1, 2020 (per NSE page reference); page last updated October 3, 2023 | Stamp duty rates by product/side |
| P6 | GST law (CGST/SGST/IGST Acts) | primary statute | 18% rate per GST Council notifications | GST rate on broker services |
| P7 | SEBI bulletin (historical STT) | https://www.sebi.gov.in/sebi_data/attachdocs/1334565322526.pdf | historical | Confirms Finance Act 2004 basis for STT |
| P8 | SEBI (Payment of Fees) (Amendment) Regulations, 2019 — SEBI/L.A.D.-N.R.O./G.N./2019/03 | https://www.sebi.gov.in/legal/regulations/mar-2019/securities-and-exchange-board-of-india-payment-of-fees-amendment-regulations-2019-dated-march-22-2019_42511.html (official regulation page and notification link) | dated 22 March 2019; fee effective April 1, 2019 | SEBI turnover fees and separate equity-option exercise/assignment turnover basis |

### 1.2 Secondary cross-checks (corroboration only)

| # | Source | URL | Use |
|---|---|---|---|
| S1 | NSE — "SEBI Turnover Fees, STT and Other levies" (info page) | https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies | Cross-checks STT table, stamp duty table, SEBI turnover fee, GST rate. Last page update October 3, 2023 — effective dates for stamp duty and SEBI fee must be verified against primary law/circulars. |
| S2 | NSE — "Securities Transaction Tax" (computation page) | https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax | Cross-checks STT computation basis (premium, traded price, intrinsic value on exercise). |
| S3 | IBKR India fee schedule | https://brokerage.ibkr.com/en/accounts/fees/indiaStockExchangeFees.php | Cross-checks NSE charges, STT, stamp duty, SEBI fee, IPFT, GST applicability. Not an originating authority. |
| S4 | CBIC — stock-broking services FAQ and GST valuation rules | https://cbic-gst.gov.in/sectoral-faq.html and https://cbic-gst.gov.in/valuation-rules.html | Official guidance on Rule 33 pure-agent treatment and fallback GST valuation under Section 15 and Rule 27; not a substitute for bill-specific treatment. |

Secondary/derived (not authoritative, used only for cross-checks): broker blogs
(stolo.in, choiceindia.com, smctradeonline.com, fyers.in). These are never the
sole basis for a verified rate.

---

## 2. Verified rates

All rates are percentages of the stated basis. "Buyer/Seller" is the liable party.
Effective dates are those stated by the cited source. Where a source does not
state an effective date, it is marked UNRESOLVED rather than invented.

### 2.1 Securities Transaction Tax (STT) — sources P1, P2, S2

Basis: transaction value (VWAP for delivery-based equity); traded value for intraday/futures; premium traded for ordinary option trades; intrinsic value for exercised options. For exercise, intrinsic value is option-kind-specific and non-negative: CALL uses max(settlement_price - strike, 0) x quantity; PUT uses max(strike - settlement_price, 0) x quantity. Option type and quantity must be explicit. This differs from the SEBI exercise turnover basis in §2.3.

Effective-date regimes (all verified against primary circulars):
- Regime A: upto September 30, 2024 (rates per P1 "upto September 30, 2024" column)
- Regime B: October 1, 2024 – March 31, 2026 (P1 effective, P2 prior column)
- Regime C: on/after April 1, 2026 (P2 effective)

| Product | Side | Regime A (≤ Sep 30 2024) | Regime B (Oct 1 2024 – Mar 31 2026) | Regime C (≥ Apr 1 2026) | Liable party | Basis |
|---|---|---|---|---|---|---|
| Equity delivery | Buy | 0.100% | 0.100% | 0.100% | Purchaser | transaction value (VWAP) |
| Equity delivery | Sell | 0.100% | 0.100% | 0.100% | Seller | transaction value (VWAP) |
| Equity intraday (non-delivery) | Sell | 0.025% | 0.025% | 0.025% | Seller | transaction value |
| Equity-oriented fund unit delivery | Buy | NIL | NIL | NIL | — | — |
| Equity-oriented fund unit delivery | Sell | 0.001% | 0.001% | 0.001% | Seller | transaction value |
| Equity futures | Sell | 0.0125% | 0.02% | 0.05% | Seller | traded price |
| Equity options | Sell (premium) | 0.0625% | 0.10% | 0.15% | Seller | premium |
| Equity options | Exercise | 0.125% | 0.125% | 0.15% | Purchaser | intrinsic value (settlement price − strike) × qty |
| Equity options | Buy | 0% | 0% | 0% | — | — |

Verified: P1 (Oct 1, 2024 effective, prior column), P2 (Apr 1, 2026 effective).
Regime A rates are stated in P1's "upto September 30, 2024" column; the start
date of that regime is not verified (P1 references earlier circulars
2/2016, 2/2018, 1/2019, 2/2019, 1/2020, 2/2023). Coverage before the
unverified start date remains UNRESOLVED — fail closed.

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

Primary statute P5 provides the statutory framework; S1 is only a secondary cross-check. Section 9A for stock-exchange/depository transactions was inserted with effect from July 1, 2020. The current applicability of every listed rate for the intended production release has not yet been reconciled against the current consolidated statute and amendments. Therefore stamp duty must remain unavailable in any complete production schedule until that primary-source review is recorded; do not ship S1-only rates as current verified production data.

### 2.3 SEBI turnover fee — source P8

| Segment | Rate | Liable party |
|---|---|---|
| Cash (equity) | 0.0001% (Rs 10 per crore) | Stock broker |
| Equity derivatives | 0.0001% (Rs 10 per crore) | Stock broker |
| Currency derivatives | 0.0001% (Rs 10 per crore) | Stock broker |
| Interest rate derivatives | 0.00005% (Rs 5 per crore) | Stock broker |
| Commodity derivatives | 0.0001% (Rs 10 per crore) | Stock broker |
| Debt | 0.00002% (Rs 2 per crore) | Stock broker |

Verified: P8 (SEBI notification SEBI/L.A.D.-N.R.O./G.N./2019/03 dated 22 March
2019, effective April 1, 2019). This resolves the previous unresolved flag:
the fee's effective date and rate are verified against the primary regulation.
Effective date of the current ₹10/crore rate — RESOLVED (P8).

**Turnover basis:** equity-option turnover uses premium traded, and when an option is exercised or assigned, turnover is additionally computed on the notional value of the exercised/assigned contract. The exercise event must therefore provide a separate rule-defined `exercise_notional_value`; do not calculate the SEBI exercise fee using STT intrinsic value or blindly reuse option premium. SEBI's legal fee payer is the stock broker. Client pass-through is a separate caller-supplied billing assumption, not established by this rate table.

### 2.4 Exchange transaction charges (NSE) — sources P3, P4

Per crore of traded value, each side (buy and sell), unless noted.

**March 1, 2026 interpretation (P4):** FA73061 does NOT increase total member
outflow. It re-splits the existing total into transaction charges + IPFT
contribution. Pre-March-1-2026: cash Rs 297 txn + Rs 10 IPFT = Rs 307 total.
Post-March-1-2026: cash Rs 306.99 txn + Rs 0.01 IPFT = Rs 307 total.
Same for futures (Rs 183.00 = 182.99 + 0.01) and options (₹3,552.99 + ₹0.01 =
₹3,553.00). The design reproduces components separately with correct effective
dates; a boundary test (T21) proves the aggregate total is unchanged across
March 1, 2026 for all three covered segments.

**Exact component values (P4):** equity options = ₹3,552.99 per crore of
premium turnover per side (transaction charges) + ₹0.01 per crore (IPFT) =
₹3,553.00 total. Cash = Rs 306.99 + Rs 0.01 = Rs 307.00. Futures = Rs
182.99 + Rs 0.01 = Rs 183.00.

**Authority boundary and pass-through assumption:** P4 specifies trading-member
outflows. The model reproduces the NSE exchange charges as configured values;
whether those are passed through to the retail client, recovered by the
broker, or absorbed by the broker is a *retail-broker tariff* question and
must be an explicit, caller-supplied assumption. This design assumes the model
reproduces NSE exchange charges as configured; it makes no claim that these
are the client-settled amounts. Any billing or recovery policy must be
supplied by the caller.

| Segment | Basis | Rate (w.e.f. Mar 1, 2026) | Rate (Oct 1, 2024 – Feb 28, 2026) | Rate (before Oct 1, 2024) |
|---|---|---|---|---|
| Cash (equity) | traded value | Rs 307.00 (306.99 txn + 0.01 IPFT) | Rs 307.00 (297 txn + 10 IPFT) | slab-wise, volume-dependent |
| Equity futures | traded value | Rs 183.00 (182.99 + 0.01) | Rs 183.00 (173 + 10) | slab-wise, volume-dependent |
| Equity options | premium value | ₹3,553.00 (₹3,552.99 + ₹0.01) | ₹3,553.00 (₹3,503 + ₹50) | slab-wise, volume-dependent |

Verified: P3 (Oct 1, 2024 uniform rates), P4 (Mar 1, 2026 revised split).
The pre-Oct-1-2024 slab-wise structure is not representable as a single rate —
see §4 (UNRESOLVED / out of scope for a single-rate schedule).

IPFT is modelled as a separate component (`ipft_rate`) for auditability, even
though it is billed within the NSE transaction charge total. Both `exchange_txn`
and `ipft` components are subject to GST (see §2.5).

### 2.5 GST — rate, taxable-base treatment, and inputs are separate

**A. Rate.** The GST rate for stockbroking services is 18% (P6; corroborated by S1/S4). The exact effective-date rule for the intended production schedule has not been fully sourced in this phase. Until then, no production GST row may be considered a complete, currently verified effective-dated rule solely from the general rate statement.

**B. Taxable-base treatment.** CBIC's stockbroking FAQ (S4) says recoveries of STT, stamp duty and other taxes are excluded from the value of supply only when the Rule 33 pure-agent conditions are met. Otherwise, valuation follows Section 15 and Rule 27. QuantX must not infer that pure-agent conditions hold from a component name.

The caller must provide an explicit, versioned treatment for each STT/stamp-duty recovery:
- `EXCLUDE_AS_QUALIFIED_PURE_AGENT` only where the caller establishes the relevant Rule 33 conditions.
- `INCLUDE_IN_TAXABLE_VALUE` where the caller's validated billing policy treats the recovery as included in taxable value.
- Missing/unknown treatment means GST is incomplete and must fail closed.

Only exchange/IPFT/SEBI components that an explicit pass-through policy says are charged to the client enter the client-side GST base. Legal payer and modeled client bearer are not interchangeable.

**C. Required inputs.** A complete GST calculation requires explicit `brokerage`, `dp_charges`, and `other_taxable_service_charges` values. Each is Decimal; `Decimal('0')` means known zero/not applicable, while `None` means unknown. Also require a pass-through policy and explicit STT/stamp-duty tax treatment.

The GST base is the sum of client-charged taxable service components (brokerage, DP charges, other supplied taxable services, and passed-through exchange transaction/IPFT/SEBI charges), plus STT or stamp duty only if the explicit policy says that recovery is included in taxable value. Qualified pure-agent exclusions are excluded. GST is then calculated on that explicit base using the applicable sourced rate.

If any required amount, pass-through decision, tax treatment or effective-dated GST rule is missing, raise an explicit incomplete-input/rule-unavailable error and return no complete `ChargeBreakdown`. Never emit a complete GST figure by silently omitting brokerage, DP or another required taxable component.

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
3. `ChargeCalculationContext` carries only transaction value and optional currency; it lacks exchange scope, explicit equity product, client trade side, event kind, separate premium/exercise bases, client pass-through policy and bill-specific GST inputs/treatment.
4. No effective-dated schedule selection mechanism for charges (the venue-rule
   snapshot pattern in `india/rule_data.py` is the reusable template).
5. No charge-specific golden tests for statutory Indian charges.
6. Paper/research execution uses `fee_bps` → `PercentageBpsChargeModel`; Indian
   statutory charges are not applied anywhere today.

---

## 4. Unresolved / unsupported cases (do not guess)

| Item | Status | Reason |
|---|---|---|
| STT prior-regime effective date (when 0.02%/0.10%/0.125% began) | RESOLVED (partial) | P1 states these as the "upto September 30, 2024" column; the start date of that regime is not verified (P1 references earlier circulars 2/2016, 2/2018, 1/2019, 2/2019, 1/2020, 2/2023). Coverage before the unverified start date remains UNRESOLVED — fail closed. |
| STT regime boundary October 1, 2024 | RESOLVED | P1 (effective October 1, 2024): futures 0.0125→0.02%, options sell 0.0625→0.10%, options exercised unchanged 0.125%. |
| STT regime boundary April 1, 2026 | RESOLVED | P2 (effective April 1, 2026): futures 0.02→0.05%, options sell 0.10→0.15%, options exercised 0.125→0.15%. |
| SEBI turnover fee effective date (current Rs 10/crore) | RESOLVED | SEBI notification SEBI/L.A.D.-N.R.O./G.N./2019/03 (22 March 2019), effective April 1, 2019 (P8). |
| Stamp duty current applicability | UNRESOLVED for production schedule | P5 provides the statutory framework and July 1, 2020 commencement of section 9A, but current consolidated rate applicability for every in-scope instrument has not been fully reconciled. No complete production schedule may use these rates until the source review is recorded. |
| GST effective-date rule for production schedule | UNRESOLVED for production schedule | The 18% rate is identified, but the applicable notification/effective date for the modeled service/components is not bound to a complete effective-dated rule. No production GST entry is complete until evidence is added. |
| GST calculation base | RESOLVED as explicit caller policy, not a universal hard-coded rule | §2.5 requires bill-specific treatment for STT/stamp recoveries, caller-supplied brokerage/DP/other taxable inputs, and client pass-through decisions for member fees. Missing inputs make GST incomplete. |
| Exchange charges before Oct 1, 2024 | UNSUPPORTED (slab-wise) | Volume-dependent slabs; cannot be represented as a single rate. Fail closed for dates before Oct 1, 2024. |
| March 2026 transaction-charge interpretation | RESOLVED (design) | P4 keeps total member outflow unchanged; re-splits into txn charges + IPFT. Components reproduced separately; boundary test (T21) proves aggregate unchanged. Applicability: cash + equity derivatives only. |
| Brokerage rates | OUT OF SCOPE | Broker-specific, not regulated. |
| DP charges | OUT OF SCOPE | DP/broker-specific. |
| Currency/commodity derivatives charges | PARTIAL | Stamp duty rates listed (S1); exchange transaction charges for currency/commodity not in P3/P4. Mark unsupported until primary source added. |
| Options exercise bases | NEEDS INPUT / separate bases | Require CALL/PUT type, quantity, settlement price and strike for STT intrinsic value, plus a separate rule-defined exercise-notional basis for SEBI fees. Never reuse one basis for the other. |
| BSE-specific charges | NOT RESEARCHED | This phase covers NSE only; exchange identity must be an explicit context field so BSE cannot accidentally use NSE rates. |
| MCX/NCDEX commodity charges | NOT RESEARCHED | Out of scope for this phase. |

---

## 5. Proposed contract (design only — not implemented)

### 5.1 New module: `src/quantx/india/charges.py`

Reuse existing infrastructure; do not modify `execution/charges.py`.

1. **`IndiaTradeSide`** enum: `BUY`, `SELL`, representing the client's side of one transaction.
2. **`IndiaChargeProduct`** enum: `EQUITY_DELIVERY`, `EQUITY_INTRADAY`, `EQUITY_FUTURES`, `EQUITY_OPTIONS`. These names constrain the first schedule to NSE equity products; fund units, currency/commodity derivatives, BSE and MCX are not aliases.
3. **`IndiaChargeEvent`** enum: `TRADE`, `OPTION_EXERCISE`. Exercise is a separate event, not a Boolean variation of an ordinary option trade.
4. **`IndiaOptionType`** enum: `CALL`, `PUT`.
5. **`IndiaRecoveryTaxTreatment`** enum: `EXCLUDE_AS_QUALIFIED_PURE_AGENT`, `INCLUDE_IN_TAXABLE_VALUE`. Missing treatment makes a complete GST result unavailable.
6. **`IndiaChargeIncidence`** enum: `CLIENT_PASSTHROUGH`, `BROKER_ABSORBED`, `NOT_APPLICABLE`.
7. **`IndiaChargePassThroughPolicy`** frozen dataclass: explicit incidence for each of `stt`, `stamp_duty`, `exchange_txn`, `ipft`, and `sebi_turnover_fee`, plus `version` and `source_ref`. Every component is classified; no implicit pass-through default. `NOT_APPLICABLE` is valid only with an explicit zero rule. This policy describes modeled client cost, not the legal payer of a member-level fee.
8. **`IndiaChargeCalculationContext`** frozen dataclass extending `ChargeCalculationContext`. Because the parent has a defaulted currency field, added fields may default to `None` but must be validated in `__post_init__`:
   - `exchange: IndianExchange | None = None` — required by validation; only NSE is supported.
   - `trade_side: IndiaTradeSide | None = None`, `product: IndiaChargeProduct | None = None`, `event: IndiaChargeEvent = TRADE`, and `effective_at: datetime | None = None` — required fields are validated before calculation.
   - `premium_value: Decimal | None = None` — required for ordinary equity-option trades; never inferred silently from underlying notional.
   - `option_type`, `quantity`, `settlement_price`, `strike`, and `exercise_notional_value` — required as applicable to `OPTION_EXERCISE`. `exercise_notional_value` is the separate SEBI turnover basis, not STT intrinsic value.
   - `brokerage: Decimal | None = None`, `dp_charges: Decimal | None = None`, `other_taxable_service_charges: Decimal | None = None` — required for complete GST; explicit `Decimal('0')` means known zero/not applicable, `None` means unknown.
   - `stt_gst_treatment`, `stamp_duty_gst_treatment`, and `pass_through_policy` — required for a complete client-side result; none has an implicit default.
9. **`IndiaChargeRateSet`** frozen dataclass: Decimal-or-None rates per component (`stt_rate`, `stamp_duty_rate`, `exchange_txn_rate`, `ipft_rate`, `sebi_turnover_rate`, `gst_rate`) plus immutable sorted `component_sources: tuple[tuple[str, str], ...]`. Rates are fractional multipliers: 0.1% is `Decimal('0.001')`, not `Decimal('0.1')`. Every component, including zero, requires source/applicability provenance. `None` means missing/unsupported and rejects the complete calculation; `Decimal('0')` means a sourced zero or explicit client-side non-liability.
10. **`IndiaChargeScheduleEntry`** frozen dataclass: `effective_from`, `effective_to` (exclusive; `None` means open-ended), non-empty `version`, and `rates` keyed by `(IndiaChargeProduct, IndiaTradeSide, IndiaChargeEvent)`. Do not use one entry-level source reference for all components.
11. **`IndiaChargeSchedule`** frozen dataclass: immutable entries. `select(effective_at)` returns the uniquely covering entry or raises `IndiaChargeRuleUnavailable`; gaps may represent explicit unsupported history.
12. **`IndiaMarketChargeModel`** implementing the existing `ChargeModel`:
   - `model_id = india.market_charges`; `model_version = 1` is the stable calculator/schema version, not the selected tariff version.
   - `calculate(context)` validates exchange is NSE, currency is INR, Decimal inputs are finite and in range, timestamps are aware, and event-specific inputs are present before computing anything.
   - Select rules by effective instant normalized against Asia/Kolkata market-time boundaries, then by `(product, side, event)`. Any missing component rule/source, unsupported scope or required input raises; no partial or zero-substituted breakdown is returned.
   - Use premium value for ordinary option components whose source basis is premium; transaction value for equity/futures; CALL/PUT intrinsic value for exercise STT; and separate `exercise_notional_value` for exercise SEBI turnover. Other event-specific component bases/rates must be sourced or unavailable.
   - Stamp duty is charged to the modeled client only on BUY. SELL-side non-liability is an explicit zero rule with provenance. Exchange/IPFT/SEBI components enter modeled client cost only according to the required caller pass-through policy.
   - GST uses the explicit taxable-base treatment and complete caller-supplied billing inputs in §2.5; missing inputs, treatment or a sourced effective-dated GST rule raises.
   - `ChargeBreakdown.provenance` identifies schedule version/interval, every component source/version, and pass-through/tax-policy references.
13. **`IndiaChargeRuleUnavailable`** — stable `ValueError` subtype for missing schedule/component rule/source or unsupported exchange/product/date/event.
14. **`IndiaChargeInputUnavailable`** — stable `ValueError` subtype for missing or incomplete event/billing/tax/pass-through inputs. Do not expose arbitrary supplied values or exception text.

### 5.2 Date selection and unsupported scope

- `effective_at` must be timezone-aware. Derive the market trading date in Asia/Kolkata. Schedule interval boundaries are the start of the effective local date; normalize aware instants so equivalent UTC/IST timestamps select the same rule.
- Inclusive/exclusive: `effective_from <= effective_at < effective_to` (`effective_from` inclusive, `effective_to` exclusive). An entry with `effective_to = None` is open-ended.
- Reject overlapping ranges. Gaps are explicit unsupported intervals: selection within a gap raises `IndiaChargeRuleUnavailable`; do not force unresolved history into invented rates.
- Schedule construction validates sorted boundaries, timezone awareness, non-empty versions, complete component mappings, source coverage, rate finiteness and non-negativity.
- Unsupported scope (fail closed, never silently fall back): BSE, MCX, NCDEX; currency/commodity derivatives; fund units and special-offer products until explicit categories/sources are reviewed; dates before the earliest fully supported entry, including pre-October-2024 slab-wise exchange charges; any absent product/side/event combination; and an exercise missing option type, quantity, settlement price, strike or SEBI exercise-notional value.
- Any missing component rate/source rejects the complete calculation. `None` means unavailable. `Decimal('0')` means a sourced zero or explicit client-side non-liability; it is not a substitute for missing data.
- Stamp-duty continuing applicability and GST effective-date coverage remain production-data gates in §4. Do not use synthetic fixtures to imply they are resolved.

### 5.3 Provenance

- The schedule version identifies the combined schedule snapshot; each component rate carries its own source/version reference. Component sources cannot be collapsed into one entry-level URL because STT, exchange/IPFT, SEBI, stamp duty and GST have different authorities/effective dates.
- `ChargeBreakdown.provenance` includes selected schedule version/interval, source/version for each component (including zeros), and caller pass-through/tax-policy references.
- `ChargeModel.model_version` is a stable implementation/schema version. It must not depend on the selected tariff entry, which is known only for a particular calculation; selected tariff version belongs in result provenance.
- Caller assumptions about member-fee pass-through and GST treatment remain distinguishable from sourced legal rates.

### 5.4 Decimal / fail-closed

- All rates/amounts use finite `Decimal` values. Rates are fractional multipliers; no float, integer, string or bool coercion is allowed for amount/rate inputs. Currency must be exactly INR.
- Negative rates, negative bases and non-positive exercise quantity are invalid. Exercise prices must be finite and non-negative.
- Missing schedule/component/provenance, unsupported scope, naive timestamp, incomplete pass-through policy, missing GST input or unknown tax treatment produces a stable fail-closed exception.
- Return `ChargeBreakdown` only if every component in the selected complete schedule is calculable. Never return a partial breakdown while claiming it is complete.
- An explicit zero component needs source/applicability provenance.

### 5.5 What stays in the universal core

`execution/charges.py` is NOT modified. The India module imports `ChargeModel`, `ChargeBreakdown`, `ChargeComponent` and `ChargeCalculationContext` from the universal core and adds India-specific logic on top. This preserves the no-Indian-tariffs-in-universal-core boundary (ADR-010, doc 52).

The first implementation slice is the contract plus synthetic test schedules only. No unverified production rates are embedded as defaults. A caller must explicitly select the India model; a missing India rule never falls back silently to a generic percentage model.

### 5.6 Calculation and rounding policy

- **Monetary base:** per trade/fill; each component uses its own source-defined basis.
- Equity delivery/intraday/futures use source-defined traded value. Ordinary equity options use premium traded wherever the source prescribes premium.
- **Option exercise:** STT uses intrinsic value (CALL: `max(settlement_price - strike, 0) x quantity`; PUT: `max(strike - settlement_price, 0) x quantity`). SEBI turnover fee uses separately supplied, rule-defined exercise notional. Missing either basis fails closed.
- All intermediate values are finite `Decimal`; no floats. Source rates are converted once to documented fractional multipliers.
- Rounding mode: `ROUND_HALF_UP` to paise per component per trade. Total is the sum of rounded component amounts, not a re-rounding of the unrounded aggregate. This is a QuantX simulation convention, not a verified exchange/statutory rule; an authoritative rule overrides it.
- **GST:** calculate only with complete explicit billing inputs, pass-through policy, and STT/stamp recovery treatments. Qualified pure-agent exclusions apply only when the caller establishes the relevant conditions.
- **Pass-through:** every member-level exchange/IPFT/SEBI fee is explicitly classified as client-pass-through, broker-absorbed or not applicable; no retail-client billing behavior is inferred from a member-outflow circular.
- **Aggregation:** per trade/fill. Client-level daily aggregation/accrual is out of scope.

## 6. Implementation sequence

1. **This document** — research/design; corrections in this branch remain docs-only.
2. Create `src/quantx/india/charges.py` with the contract above. No hardcoded production rates; rates are supplied schedule data.
3. Add unit tests at `tests/unit/india/test_market_charges.py` using clearly named synthetic schedule fixtures for arithmetic, effective dates, provenance, event-specific bases, rounding and fail-closed behavior. Synthetic fixtures do not prove tariff correctness.
4. In a separate slice, add versioned schedule data and a loader. Populate a component/date/product only after its rate, basis, liability, effective date and source are verified. Stamp-duty and GST production entries remain unavailable until source gates in §4 are closed.
5. In a separate slice, wire into paper/research execution only when the India model is explicitly selected and a complete supported schedule exists. For an India context, missing/unverified rules raise `IndiaChargeRuleUnavailable`; never fall back silently to `PercentageBpsChargeModel`. The generic model may be explicitly selected for a clearly labelled generic simulation, not used as an India-rule fallback.
6. Update docs/architecture/52-transaction-cost-and-charges.md and the India skill only after implementation is accepted and verified.

Do not bundle steps 2–6 into one change. Each is a separate, reviewable slice. Do not change production source, roadmap or `docs/STATUS.md` in this design-reconciliation commit.

## 7. Acceptance matrix

**Test-fixture rule:** T1–T21 are calculation/schedule-selection mechanics using synthetic fixtures where necessary; they do not prove every rate is approved for production. Source-verified tariff golden tests must separately use only component/date combinations approved in §4. Until stamp-duty and GST effective-date gates are closed, no production all-in schedule may claim those components are supported for those dates.

| # | Test | Expected |
|---|---|---|
| T1 | Equity delivery BUY, Rs 10,000, fully specified synthetic schedule | Uses delivery STT basis and buyer stamp-duty rule; GST succeeds only with explicit complete billing/tax/pass-through inputs |
| T2 | Equity delivery BUY on Friday, March 13, 2026 | Delivery STT 0.1%; transaction-charge regime is post-Mar-1 and pre-Apr-1 STT regime |
| T3 | Equity intraday SELL, Rs 10,000 | STT 0.025% on seller transaction; client stamp duty zero because buyer-liable; eligible charges follow client pass-through policy |
| T4 | Equity futures SELL on/after Apr 1, 2026 | STT 0.05% on traded value; client stamp duty zero on SELL; exchange fee basis is traded value |
| T5 | Equity futures SELL on Friday, Feb 13, 2026 | STT 0.02%; transaction-charge schedule is pre-Mar-1 regime |
| T6 | Equity options SELL, premium Rs 5,000, after Apr 1, 2026 | STT 0.15% on premium; client stamp duty zero on SELL; exchange/IPFT/SEBI use premium turnover basis |
| T7 | Equity options SELL on Friday, Mar 13, 2026 | STT 0.10%; post-Mar-1 exchange/IPFT split, aggregate Rs 3,553/crore |
| T8 | Equity option exercise for CALL and PUT | STT uses correct non-negative intrinsic value; SEBI turnover uses separate exercise notional; missing event-specific component rule blocks |
| T9 | Trade before Oct 1, 2024 | `IndiaChargeRuleUnavailable` for complete all-in schedule because pre-boundary exchange rates are slab-wise and unsupported |
| T10 | Unsupported product such as currency futures | `IndiaChargeRuleUnavailable` |
| T11 | Equity intraday BUY where STT rate is sourced zero | STT zero is valid with provenance; it is not confused with missing `None` |
| T12 | Missing source for any component, including a zero rate | Schedule construction/calculation fails; zero does not waive source coverage |
| T13 | Naive `effective_at` | `ValueError`; fail closed |
| T14 | Non-Decimal or non-finite amount/rate, negative basis, non-INR currency | Rejected before calculation; no coercion |
| T15 | Negative rate | `ValueError` |
| T16 | GST base with brokerage, DP and other taxable-service inputs plus policy-defined pass-through | Exact GST on complete explicit base; missing required input/treatment refuses |
| T17 | Schedule boundary at Apr 1, 2026 00:00 IST | New effective interval selected; effective-from inclusive |
| T18 | Schedule instant one second before Apr 1, 2026 00:00 IST | Prior interval selected; effective-to exclusive |
| T19 | `ChargeBreakdown.total` | Equals exact sum of rounded components |
| T20 | Provenance | Contains schedule version/interval, each component source/version and billing/pass-through policy references |
| T21 | Schedule-selection boundary before/at Mar 1, 2026 00:00 IST; not claims of trading sessions | Exchange+IPFT total stays unchanged: cash 306.99+0.01=307, futures 182.99+0.01=183, options 3,552.99+0.01=3,553 per crore; split changes |
| T22 | Stamp-duty current applicability remains unresolved | A complete production schedule is rejected; S1-only rates are not accepted as current verified production rules |
| T23 | Brokerage or DP amount missing, or GST treatment missing | `IndiaChargeInputUnavailable`; no supposedly complete GST amount |
| T24 | GST treatment excludes STT/stamp only with a supplied qualified-pure-agent decision | Base follows explicit policy; absent policy refuses; test exclusion and inclusion paths |
| T25 | Same underlying trade with client BUY vs SELL | Stamp duty charged only on client BUY; SELL has explicit source-backed zero for client liability |
| T26 | Exchange BSE/MCX/NCDEX or missing exchange | `IndiaChargeRuleUnavailable` before returning any component |
| T27 | CALL and PUT exercises with positive/negative/zero raw intrinsic differences | Intrinsic value uses correct direction and is never negative |
| T28 | Exercise STT basis vs SEBI basis | STT uses intrinsic value; SEBI uses exercise notional; one cannot substitute for the other |
| T29 | Missing client fee-incidence/pass-through classification | `IndiaChargeInputUnavailable`; no assumed retail pass-through |
| T30 | Model identity vs tariff identity | `model_version` remains implementation version; selected schedule version and component sources are in provenance |

The former Sunday-dated T2/T5 examples are changed to real trading dates. T17/T18/T21 are schedule-selection boundary tests, not simulated executions on a non-trading session.

## 8. Out of scope (do not implement in this slice)

- New accounting engine or replacing `execution/charges.py`.
- Hardcoding unverified rates in production code.
- Brokerage, DP charges (broker-specific).
- BSE/MCX/NCDEX charge schedules.
- Currency/commodity derivatives, fund units and special-offer products until explicit product categories and primary-source schedules are added.
- SEBI compliance layer (ADR-010).
- LIVE broker receipt charges (separate slice, needs authoritative broker evidence).
- #267 (risk-evidence authority) and #266 (daily-loss semantics) — tracked separately.

---

## 9. Unresolved questions

1. Who owns and validates the caller-supplied GST/billing policy, including pure-agent treatment and the components billed to the client? This is an explicit input contract, not a legal determination by QuantX.
2. Should schedule data be loaded from a Python module or versioned JSON/YAML? (Proposed: Python module, consistent with `india/rule_data.py`.)
3. Keep IPFT separate for auditability, even though it participates in the published NSE member outflow.
4. BSE support remains separate scope; NSE first.
5. Pre-Oct-1-2024 slab-wise exchange charges remain unsupported until a separate volume-tiered design is justified.
6. Which authoritative consolidated stamp-duty source and GST rate notification will close the production data gates in §4? Until resolved, those production entries remain unavailable.
7. Confirm that the caller's pass-through policy represents client economic incidence while source provenance separately records the legal fee payer/member outflow.

---

## 10. Evidence status

- **Structural inspection:** `execution/charges.py`, `india/execution_rules.py`,
  `india/rule_data.py`, `india/domain.py`, `research/provenance.py`,
  `research/point_in_time.py`, `tests/unit/execution/test_charges.py`,
  `docs/architecture/52-transaction-cost-and-charges.md` — all read.
- **Runtime/test/CI evidence:** none collected in this phase. No tests run,
  no code changed. The only checks run were repository-integrity checks on
  the skill library (unrelated to this task).
- **Source research:** web search + primary-source review (P1–P8 above); S1–S4 are secondary cross-checks/guidance and do not establish every primary rate or effective date.
  Rates marked UNRESOLVED are not verified and must not be used in
  implementation until resolved.
