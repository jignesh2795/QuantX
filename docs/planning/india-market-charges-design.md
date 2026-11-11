# QX-12 / #200 — India Market Charges: Source Inventory and Design

**Implementation branch:** `integration/issue200-current-main-v1` (core per-trade charge contract).
**Phase:** The per-trade India charge contract and T21 schedule-boundary tests are implemented. Production tariff activation and execution integration remain deferred pending authoritative rate/effective-date and worked-example approval. Physical-delivery settlement research is retained below as a future, non-blocking research register; its calculator, State/UT resolver and clearing-specific tests are excluded from Issue #200.
**Scope:** NSE India per-trade charges for cash-equity delivery, intraday, futures and options trades, plus explicitly modeled option exercise where supported. Physical delivery of stock derivatives and clearing-member back-office reconciliation are excluded.

## 1. Source inventory

Sources are split into **primary authorities** (exchange circulars, applicable
legislation, and regulatory circulars that originate the rate) and **secondary
cross-checks** (broker/exchange-published info pages and third-party brokers).
S1–S3 are cross-checks, not originating authorities. S4 is official CBIC administrative guidance on GST valuation, not the primary rate notification itself. Supporting sources may explain treatment but never silently override a statute, rate notification, or exchange circular. Where current applicability/effective date is not established by the governing primary authority, it remains UNRESOLVED rather than being inferred from a secondary page.

### 1.1 Primary authorities

| # | Source | URL | Date stated | Covers |
|---|---|---|---|---|
| P1 | NSE circular FATAX63809 (STT, Finance Act 2024) | https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf | dated September 9, 2024; effective October 1, 2024 | STT: options sell 0.0625→0.10%, futures 0.0125→0.02%; prior rates upto September 30, 2024 |
| P2 | NSE circular FATAX73524 (STT, Finance Act 2026) | https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf | dated March 31, 2026; effective April 1, 2026 | STT: options sell 0.10→0.15%, options exercised 0.125→0.15%, futures 0.02→0.05% |
| P3 | NSE circular FA64232 (transaction charges, SEBI circular SEBI/HO/MRD/TPD-1/P/CIR/2024/92) | https://nsearchives.nseindia.com/content/circulars/FA64232.pdf | dated September 27, 2024; effective October 1, 2024 | Uniform (non-slab) exchange transaction charges: cash Rs 2.97/lakh, futures Rs 1.73/lakh, options Rs 35.03/lakh each side |
| P4 | NSE circular FA73061 (transaction charges + IPFT split) | https://nsearchives.nseindia.com/content/circulars/FA73061.pdf | dated February 27, 2026; effective March 1, 2026 | Revised split per crore each side: cash ₹306.99 transaction + ₹0.01 IPFT = ₹307; futures ₹182.99 + ₹0.01 = ₹183; options ₹3,552.99 + ₹0.01 = ₹3,553.00. The PDF table image was inspected because text extraction omits the options .99 decimals; total Trading Member outflow is unchanged |
| P5 | Indian Stamp Act 1899 as amended, including section 9A and Schedule I | https://upload.indiacode.nic.in/showfile?actid=AC_CEN_2_2_00036_189902_1523339055436&filename=a1899-2.pdf&type=actfile | Article 56A inserted by Finance Act 2019, effective July 1, 2020; section 9A governs collection for exchange transactions | Primary statutory rates, instrument classes and buyer collection. The 0.015% delivery and 0.003% non-delivery categories are relevant to the physical-settlement method described in P13 Item 21; no production schedule is activated.
| P6 | Notification No. 11/2017-Central Tax (Rate), as amended, with corresponding SGST/IGST notifications | https://cbic-gst.gov.in/hindi/pdf/central-tax-rate/Notification11-CGST.pdf; classification annexure: https://cbic-gst.gov.in/hindi/pdf/central-tax-rate/Notification11-CGST-Annexure.pdf | dated June 28, 2017; GST commencement July 1, 2017 | Financial and related services under Heading 9971: 9% CGST + 9% SGST / 18% IGST; SAC 997152 identifies brokerage and related securities services. Current CBIC rate table remains 9/9/18. Invoice-specific taxable-base and recovery treatment remain separate from the rate |
| P7 | SEBI bulletin (historical STT) | https://www.sebi.gov.in/sebi_data/attachdocs/1334565322526.pdf | historical | Confirms Finance Act 2004 basis for STT |
| P8 | SEBI (Payment of Fees) (Amendment) Regulations, 2019 — SEBI/L.A.D.-N.R.O./G.N./2019/03 | https://www.sebi.gov.in/legal/regulations/mar-2019/securities-and-exchange-board-of-india-payment-of-fees-amendment-regulations-2019-dated-march-22-2019_42511.html | dated 22 March 2019; historical fee basis effective April 1, 2019 | Historical ₹10/crore equity-derivatives turnover fee and option premium / exercise-assignment notional basis under the 1992 regulations; superseded as the current instrument by P9 from January 7, 2026 |
| P9 | Securities and Exchange Board of India (Stock Brokers) Regulations, 2026 — Notification SEBI/LAD-NRO/GN/2026/291 | https://www.sebi.gov.in/legal/regulations/jan-2026/securities-and-exchange-board-of-india-stock-brokers-regulations-2026_98974.html; Gazette PDF: https://www.sebi.gov.in/sebi_data/attachdocs/jan-2026/1767852346757.pdf | notified and effective on publication in the Official Gazette, January 7, 2026 (SEBI listing dated January 8, 2026) | Current Regulation 41: equity derivatives 0.00010% of turnover (₹10/crore); option turnover is premium traded plus notional value where exercised or assigned. Regulation 51 repeals the 1992 Stock Brokers Regulations |
| P10 | NSE Clearing — Securities Transaction Tax (STT) computation | https://www.nseclearing.in/clearing-settlement/equity-derivatives/securities-transaction-tax | Operational guidance page states updated August 1, 2025 | Confirms additional delivery-based equity STT also applies to physically settled stock futures and options, payable by both purchaser/receiver and seller/giver, in addition to ordinary derivative-trade STT and the option-exercise intrinsic-value rule |
| P11 | SEBI (Payment of Fees) (Amendment) Regulations, 2020 — SEBI/LAD-NRO/GN/2020/011 | https://www.sebi.gov.in/sebi_data/attachdocs/may-2020/1589196249922.pdf | dated May 8, 2020; effective June 1, 2020 | Temporary 50% reduction in percentage-based fees for equity-derivatives turnover from June 1, 2020 through March 31, 2021; historical exception only, outside the current supported exchange-charge range |
| P12 | NSE Clearing F&O Consolidated Circular 053/2024 — NCL/CMPT/61801 | https://avantiscdnprodstorage.blob.core.windows.net/legalupdatedocs/31619/NSE_issued_the_Consolidated_Circular_on_FO_Segment_of_NCL_Apr292024.pdf | dated April 29, 2024 | Primary PDF reviewed: Item 5.4.3 permits cross-segment settlement-obligation netting only for common clearing-member/trading-member/client-UCC on the same security, but expressly keeps F&O physical and Capital Market stamp duty separate. Item 21.1 determines the applicable State/UT from the client code (member code is deemed the client code for proprietary transactions) and falls back to the trading-member State/UT only when client State/UT is unavailable; it also establishes trade-level futures/option bases and receiver-side physical stamp duty on final settlement price. Item 21.2.1.3 defines physical-settlement BQTY/SQTY netting, two-decimal component rounding; Item 21.2.2 applies nearest-rupee client-level rounding (50 paise and above up). Item 21.2.3/21.2.4 aggregate client totals to TM/CM. Item 21.3 identifies F_SD03 (TM delivery-settlement stamp-duty report) and F_SD04 (CM delivery-settlement stamp-duty report). NCL does not collect stamp duty in respect of Sikkim clients |
| P13 | NSE Clearing F&O Consolidated Circular 050/2026 — NCL/CMPT/73997 | https://www.nseindia.com/static/resources/consolidated-master-circulars | dated April 30, 2026 | Operator-reported download and inspection of the official ZIP and Part B Items 6 and 21. The report states that delivery-based equity STT also applies to physically settled stock derivatives and that Item 21 covers client-code/State-UT fallback, BQTY/SQTY aggregation, delivery/non-delivery rates, rounding and F_SD03/F_SD04 reports. Binary source/cell-level findings remain operator-reported until independently inspected.
| P14 | SEBI Circular HO/47/11/11(3)2025-MRD-POD2/I/23843/2026 — Review of CAS, market timings and derivatives settlement methodology | https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792079571420.pdf | dated October 15, 2026; effective December 7, 2026 (with separate February 8, 2027 order-transition provisions) | Revised derivative expiry settlement-price methodology. Stock derivatives use underlying stock VWAP across exchanges over the last 30 minutes of CTS; index derivatives use an index value derived from constituent-stock VWAPs. P15 Annexure A is now reported inspected and describes operational branches/fallbacks, but contains unresolved cross-reference/rounding wording; do not implement price derivation or fallback until those ambiguities are closed.
| P15 | NSE Clearing circular NCL/CMPT/77212 — Updated SOP on Settlement Price computation | https://www.archive.nseclearing.in/content/circulars/CMPT77212.zip | dated October 30, 2026 | Operator-reported official ZIP retrieval: 254,391 bytes; SHA-256 `AD0B8A92C451F1B1DB30962175451DE4719E9A24A396FCDC2C7AAB7702DA173F`. Annexure A is reported inspected. §2.2.1 sets stock-derivative settlement-price branches (multi-exchange last-30-minute VWAP, one-exchange price, intraday LTP/simple average, previous settlement if no trade); wording in the no-last-30-minute-trade branch (“point 1 and 2”) and scenario-3 rounding are ambiguous. §2.2.2 does not explicitly specify the index constituent-VWAP formula. Keep unresolved cases blocked.

### 1.2 Supporting sources and administrative guidance

| # | Source | URL | Use |
|---|---|---|---|
| S1 | NSE — "SEBI Turnover Fees, STT and Other levies" (info page) | https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies | Current cross-check page (updated April 17, 2026) for STT, stamp duty and SEBI fee tables; secondary to P1/P2/P5/P8/P9/P10 for originating authority. |
| S2 | NSE — "Securities Transaction Tax" (computation page) | https://www.nseindia.com/static/products-services/equity-derivatives-securities-transaction-tax | Cross-checks STT computation basis (premium, traded price, intrinsic value on exercise) and the currently published delivery-rate table; P10 is the operational source for additional physically-settled stock-derivative STT. |
| S3 | IBKR India fee schedule | https://brokerage.ibkr.com/en/accounts/fees/indiaStockExchangeFees.php | Cross-checks NSE charges, STT, stamp duty, SEBI fee, IPFT, GST applicability. Not an originating authority. |
| S4 | CBIC — stock-broking services FAQ and GST valuation rules | https://cbic-gst.gov.in/sectoral-faq.html and https://cbic-gst.gov.in/valuation-rules.html | Official guidance on Rule 33 pure-agent treatment and fallback GST valuation under Section 15 and Rule 27; not a substitute for bill-specific treatment. |
| S5 | Searchable third-party transcription of NCL/CMPT/73997 Part B / Item 21 | https://www.scribd.com/document/1048030393/PART-B | Corroborates the physical-settlement stamp-duty language found in P12 (State/UT fallback, buy/sell position aggregation, final-settlement-price values and rounding). It is not an authenticated NCL source and cannot close P13 by itself. |
| S6 | NSE Clearing UDiFF Annexures B/C | https://www.nseclearing.in/udiff | Annexure B `.xlsx` and Annexure C `.zip`; official page reports last update 14 May 2026 | Official published schemas/sample files. Operator reports 38 StampDuty and 49 STTCTT field definitions aligned across P13 Part E and Annexure B by field ID/name/type-size. Annexure C's FOPHY sample has a duplicate `TtlSellTrfVal` header and lacks a distinct `TtlSellTradgVol`; treat this as a sample anomaly, not a schema change. Row-level values/cardinality/joins remain unvalidated.

Secondary/derived (not authoritative, used only for cross-checks): broker blogs
(stolo.in, choiceindia.com, smctradeonline.com, fyers.in). These are never the
sole basis for a verified rate.

---

## 2. Verified rates

All rates are percentages of the stated basis. "Buyer/Seller" is the liable party.
Effective dates are those stated by the cited source. Where a source does not
state an effective date, it is marked UNRESOLVED rather than invented.

### 2.1 Securities Transaction Tax (STT) — sources P1, P2, P10, S1/S2

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

Verified: P1 (effective October 1, 2024) and P2 (effective April 1, 2026). Regime A rates are stated in P1's "upto September 30, 2024" column; the beginning of that prior regime is not verified, so dates before the earliest fully supported schedule remain UNRESOLVED — fail closed.

**Additional STT on physical settlement of stock derivatives (P10/P12):** NSE Clearing states that STT at the rate applicable to delivery-based equity transactions also applies when stock futures or stock options are physically settled. Both purchaser/receiver and seller/giver are liable. The current delivery-based equity rate is 0.10% for both sides. This is distinct from (a) ordinary sell-side STT on futures/options trades and (b) option-exercise STT on intrinsic value. P12 Item 5.4.1 defines settlement roles from positions: long futures and long exercised calls receive securities; short futures and short assigned calls deliver; long exercised puts deliver; short assigned puts receive. Each settlement side must be explicitly represented; the original derivative BUY/SELL label is not itself the delivery role. Keep the exact applicable STT delivery-value basis tied to the authoritative settlement price/obligation evidence; do not silently reuse trade notional or option intrinsic value.

### 2.2 Stamp duty — primary statute P5; S1 is a current cross-check

| Product / transaction | Rate | Liable party |
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

**Resolved for the standard in-scope NSE transaction classes:** Article 56A of Schedule I to the Indian Stamp Act specifies the rates above; section 9A provides that stamp duty on exchange transactions is collected from the buyer on the market value at settlement. The Article 56A amendment was made by the Finance Act 2019 and took effect July 1, 2020. NSE's current investor table continues to publish the same buyer-side rates. These are no longer an S1-only cross-check.

**Physical-settlement stamp duty — methodology and current-version source acquisition:** NSE Clearing's P12/P13 method uses client-code/State-UT determination, permitted member fallback, and per-client/security/day BQTY/SQTY aggregation: BDQTY = max(BQTY − SQTY, 0), BNDQTY = min(BQTY, SQTY). The sources identify delivery/non-delivery bases and separate paise-level component rounding with a nearest-rupee client total. P13 Item 21 is now reported inspected from the official ZIP, so the earlier 'current-version cross-check pending' status is superseded. The operator reports F_SD03/F_SD04 and the UDiFF StampDuty/STTCTT schemas; actual row-level member samples and cross-report join correctness remain unproven. This is not a flat additional 0.015% on all physically settled value and cannot be calculated from a single trade/fill context. The distinct physical-delivery STT leg and exercised-option intrinsic STT overlap still require tax/clearing interpretation.

### 2.3 SEBI turnover fee — current source P9; historical source P8

| Segment | Rate | Liable party |
|---|---|---|
| Cash (equity) | 0.0001% (Rs 10 per crore) | Stock broker |
| Equity derivatives | 0.0001% (Rs 10 per crore) | Stock broker |
| Currency derivatives | 0.0001% (Rs 10 per crore) | Stock broker |
| Interest rate derivatives | 0.00005% (Rs 5 per crore) | Stock broker |
| Commodity derivatives | 0.0001% (Rs 10 per crore) | Stock broker |
| Debt | 0.00002% (Rs 2 per crore) | Stock broker |

Historical rule: P8 amended the 1992 Stock Brokers Regulations in March 2019 and established the ₹10/crore rate from April 1, 2019. P11 temporarily reduced percentage-based fees for equity-derivatives turnover to 50% from June 1, 2020 through March 31, 2021. That temporary period lies outside the current supported schedule history (the pre-October-1-2024 exchange-charge structure is slab-wise and unsupported), but it must be represented if the schedule is ever backdated into that interval. Current rule: P9, Regulation 41 of the SEBI (Stock Brokers) Regulations, 2026, retains the equity-derivatives fee at 0.00010% (₹10/crore); it includes trades executed and trades settled on contract expiry. For options, turnover comprises premium traded plus the additional notional value where the contract is exercised or assigned. P9 took effect on publication in the Official Gazette on January 7, 2026 and Regulation 51 repealed the 1992 regulations. SEBI fees are broker/clearing-member liabilities; client pass-through remains a separate caller-supplied billing assumption.

**Turnover basis:** equity-option turnover uses premium traded, and when an option is exercised or assigned, turnover is additionally computed on the notional value of the exercised/assigned contract. The exercise event must therefore provide a separate rule-defined `exercise_notional_value`; do not calculate the SEBI exercise fee using STT intrinsic value or blindly reuse option premium. SEBI's legal fee payer is the stock broker. Client pass-through is a separate caller-supplied billing assumption, not established by this rate table.

### 2.4 Exchange transaction charges (NSE) — sources P3, P4

Per crore of traded value, each side (buy and sell), unless noted.

**March 1, 2026 interpretation (P4):** FA73061 does NOT increase total member
outflow. It re-splits the existing total into transaction charges + IPFT
contribution. Pre-March-1-2026: cash Rs 297 txn + Rs 10 IPFT = Rs 307 total.
Post-March-1-2026: cash Rs 306.99 txn + Rs 0.01 IPFT = Rs 307 total.
Same for futures (Rs 183.00 = 182.99 + 0.01) and options (₹3,552.99 + ₹0.01 =
₹3,553.00). The schedule contract supports independently versioned transaction-charge and IPFT components. The T21 synthetic boundary test passed at exact follow-up HEAD `ca0ceb606c867c3f98309223e9c7a170b42deb9b`: eight cases across cash delivery, cash intraday, futures and options premium, BUY and SELL. The operator reported default and Dhan canonical full suites and release gates PASS at that SHA. Pass-through in the fixture is explicit and synthetic only; it does not establish universal broker billing. This contract-only implementation embeds no production tariff data.

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
though it contributes to the NSE trading-member outflow. Whether transaction charges/IPFT are passed through to the client is a caller-supplied policy. GST treatment applies only to the client-charged components and explicit bill-specific tax policy in §2.5; it is not an unconditional assertion for every member-outflow component.

### 2.5 GST — rate, taxable-base treatment, and inputs are separate

**A. Rate and classification.** Notification No. 11/2017-Central Tax (Rate) (P6), dated June 28, 2017, classifies financial and related services under Heading 9971 at 9% CGST plus 9% SGST, or 18% IGST. The notification's service-classification annexure identifies SAC 997152 as brokerage and related securities/commodities services. The current CBIC consolidated rate table continues to show 9% / 9% / 18% for the relevant Heading 9971 financial-services entry. For the standard stock-broking service, the 18% rate and July 1, 2017 GST commencement are RESOLVED. This does not determine the taxable base for each invoice or imply that every statutory/member-level charge is taxable.

**B. Taxable-base treatment.** CBIC's stockbroking FAQ (S4) says recoveries of STT, stamp duty and other taxes are excluded from the value of supply only when the Rule 33 pure-agent conditions are met. Otherwise, valuation follows Section 15 and Rule 27. QuantX must not infer that pure-agent conditions hold from a component name.

The caller must provide an explicit, versioned treatment for each STT/stamp-duty recovery:
- `EXCLUDE_AS_QUALIFIED_PURE_AGENT` only where the caller establishes the relevant Rule 33 conditions.
- `INCLUDE_IN_TAXABLE_VALUE` where the caller's validated billing policy treats the recovery as included in taxable value.
- Missing/unknown treatment means GST is incomplete and must fail closed.

Only exchange/IPFT/SEBI components that an explicit pass-through policy says are charged to the client enter the client-side GST base. Legal payer and modeled client bearer are not interchangeable.

**C. Required inputs.** A complete GST calculation requires explicit `brokerage`, `dp_charges`, and `other_taxable_service_charges` values. Each is Decimal; `Decimal('0')` means known zero/not applicable, while `None` means unknown. Also require a pass-through policy and explicit STT/stamp-duty tax treatment.

The GST base is the sum of client-charged taxable service components (brokerage, DP charges, other supplied taxable services, and passed-through exchange transaction/IPFT/SEBI charges). STT or stamp duty may be added only when (a) the component is actually charged to the client under the pass-through policy and (b) its explicit tax-treatment input is `INCLUDE_IN_TAXABLE_VALUE`. A `EXCLUDE_AS_QUALIFIED_PURE_AGENT` decision excludes that recovery only when the caller has established Rule 33 conditions. If incidence or tax treatment is absent or contradictory, GST is incomplete. GST is then calculated on that explicit base using the applicable sourced rate.

If any required amount, pass-through decision, tax treatment or effective-dated GST rule is missing, raise an explicit incomplete-input/rule-unavailable error and return no complete `ChargeBreakdown`. Never emit a complete GST figure by silently omitting brokerage, DP or another required taxable component.

### 2.6 Brokerage and DP charges — NOT universal

Brokerage is not regulated by SEBI (caps removed in 2003) and varies by
broker/plan. DP (depository participant) charges vary by DP/broker. These are
out of scope for a universal schedule and must remain caller-supplied
configuration, not embedded in the India schedule.

---

## 3. Implementation status against the original design baseline

The original gap assessment predates the first contract-only implementation slice. The current disposition is:

1. **India-specific calculator contract — implemented in the current candidate.** `src/quantx/markets/india/charges.py` composes the existing market-neutral `ChargeModel` / `ChargeBreakdown` contract with India exchange, product, side, event, effective-time, pass-through, tax-treatment and provenance inputs.
2. **Effective-dated selection and fail-closed rule behavior — implemented in the current candidate.** Immutable schedule entries select by timezone-aware Asia/Kolkata effective intervals; unsupported dates, products, sides, events and missing component rates/sources do not become zero.
3. **Synthetic calculation tests — implemented in the current candidate.** `tests/unit/markets/india/test_charges.py` covers arithmetic, premium and exercise bases, schedule boundaries, provenance, incidence, GST inputs, rounding and unsupported cases. Synthetic fixtures do not prove tariff correctness.
4. **Production tariff schedule/loader — NOT IMPLEMENTED.** No production rates or effective-dated production schedule are embedded. Standard statutory and exchange rates have source references, and P13/P15 current-source acquisition is now operator-reported complete. Production schedule approval remains blocked by unresolved commencement/effective-date questions, STT event/base interaction, final-settlement-price wording, clearing reconciliation and golden worked examples.
5. **Paper/research execution integration — NOT IMPLEMENTED.** Existing execution still uses the generic configured `PercentageBpsChargeModel`; the India model is not automatically selected or wired into execution.
6. **Physical-settlement clearing/tax calculator — DEFERRED; not part of Issue #200.** A historical contract-only experiment exists on a separate feature branch, but its code and dedicated tests are excluded from the current-main per-trade charge candidate. Do not add State/UT domicile resolution, client/security/day clearing aggregation, F_SD03/F_SD04 ingestion, physical-delivery STT, or F&O physical-settlement stamp-duty calculation to this issue. Preserve the source research as a future reference only; a separate milestone is justified only when QuantX deliberately supports carrying stock derivatives through physical delivery.

The public `quantx.execution.charges` compatibility import path and generic percentage model remain available, but canonical ownership of the four neutral charge contracts moved to `quantx.ports.charges`. The execution module now re-exports those same objects by identity.

## 4. Unresolved / unsupported cases (do not guess)

| Item | Status | Reason |
|---|---|---|
| STT prior-regime effective date (when 0.02%/0.10%/0.125% began) | RESOLVED (partial) | P1 states these as the "upto September 30, 2024" column; the start date of that regime is not verified (P1 references earlier circulars 2/2016, 2/2018, 1/2019, 2/2019, 1/2020, 2/2023). Coverage before the unverified start date remains UNRESOLVED — fail closed. |
| STT regime boundary October 1, 2024 | RESOLVED | P1 (effective October 1, 2024): futures 0.0125→0.02%, options sell 0.0625→0.10%, options exercised unchanged 0.125%. |
| STT regime boundary April 1, 2026 | RESOLVED | P2 (effective April 1, 2026): futures 0.02→0.05%, options sell 0.10→0.15%, options exercised 0.125→0.15%. |
| SEBI turnover fee (current ₹10/crore equity-derivatives rate) | RESOLVED for current rule; historical exception documented | P9 Regulation 41 retains 0.00010% / ₹10 per crore and states the option premium plus exercise/assignment notional basis. P9 took effect January 7, 2026 and repealed the 1992 regulations. P8 is the predecessor source, with P11's 50% temporary reduction applying June 1, 2020–March 31, 2021; that interval is outside the currently supported all-in schedule range. |
| Standard stamp-duty rates for NSE equity delivery, intraday, futures and options | RESOLVED from July 1, 2020 | P5 Article 56A and section 9A establish the statutory schedule and buyer collection. NSE's current table cross-checks the same rates. This status does not resolve the separate physical-settlement derivative question below. |
| Standard stock-broking GST rate and effective start | RESOLVED (18% from July 1, 2017) | P6 Notification 11/2017, the SAC 997152 classification annexure and the current CBIC rate table support 9% CGST + 9% SGST / 18% IGST for the financial-services entry. The taxable base remains invoice-specific and must follow Section 15 / Rule 27 and Rule 33 pure-agent conditions. |
| GST calculation base | RESOLVED as explicit caller policy, not a universal hard-coded rule | §2.5 requires bill-specific treatment for STT/stamp recoveries, caller-supplied brokerage/DP/other taxable inputs, and client pass-through decisions for member fees. Missing inputs make GST incomplete. |
| Exchange charges before Oct 1, 2024 | UNSUPPORTED (slab-wise) | Volume-dependent slabs; cannot be represented as a single rate. Fail closed for dates before Oct 1, 2024. |
| March 2026 transaction-charge interpretation | RESOLVED; synthetic runtime test accepted | P4 keeps the published Trading Member fee total unchanged and re-splits it into transaction charges + IPFT. T21 passed operator-reported default and Dhan exact-HEAD canonical producer/release gates at `ca0ceb606c867c3f98309223e9c7a170b42deb9b`: eight cases cover cash delivery/intraday, futures and options premium, BUY and SELL. Pass-through is synthetic only and is not a universal broker billing policy. Applicability: cash + equity derivatives only. |
| Brokerage rates | OUT OF SCOPE | Broker-specific, not regulated. |
| DP charges | OUT OF SCOPE | DP/broker-specific. |
| Currency/commodity derivatives charges | PARTIAL | Stamp duty rates listed (S1); exchange transaction charges for currency/commodity not in P3/P4. Mark unsupported until primary source added. |
| Option exercise STT / SEBI bases | RESOLVED as separate bases; assignment unsupported | P10 states option-exercise STT is based on intrinsic value; P9 Regulation 41 uses premium turnover plus additional notional value when exercised or assigned. The calculator already requires separate exercise notional for SEBI and keeps assignment unsupported. Never substitute one basis for the other. |
| Physically settled stock-derivative STT | DEFERRED / OUT OF SCOPE | This is a separate share-transfer tax event, not an ordinary order/fill charge. No physical-delivery STT calculator or complete physical-settlement result is part of Issue #200. |
| Physical-settlement stamp-duty rule | DEFERRED / OUT OF SCOPE | NCL clearing aggregation, State/UT domicile resolution, Sikkim collection disposition, F_SD03/F_SD04 reconciliation and delivery-specific rounding do not belong to the per-trade charge calculator. Research is retained in §8 for a possible later milestone. |
| BSE-specific charges | NOT RESEARCHED | This phase covers NSE only; exchange identity must be an explicit context field so BSE cannot accidentally use NSE rates. |
| MCX/NCDEX commodity charges | NOT RESEARCHED | Out of scope for this phase. |

---

## 5. Implemented contract

### 5.1 New module: `src/quantx/markets/india/charges.py`

Reuse the vendor- and market-neutral charge contracts in `quantx.ports.charges`. Preserve the existing `quantx.execution.charges` import path as an identity-preserving compatibility facade; keep the generic percentage model execution-owned.

1. **`IndiaTradeSide`** enum: `BUY`, `SELL`, representing the client's side of one transaction.
2. **Assignment boundary:** `OPTION_ASSIGNMENT` is represented explicitly in the event enum but remains unsupported in the first slice. It raises `IndiaChargeRuleUnavailable`; do not infer assignment from `OPTION_EXERCISE` or a normal SELL trade. Support it only after source-backed payer, turnover-basis and component rules are specified.
3. **`IndiaChargeProduct`** enum: `EQUITY_DELIVERY`, `EQUITY_INTRADAY`, `EQUITY_FUTURES`, `EQUITY_OPTIONS`. These names constrain the first schedule to NSE equity products; fund units, currency/commodity derivatives, BSE and MCX are not aliases.
4. **`IndiaChargeEvent`** enum: `TRADE`, `OPTION_EXERCISE`, `OPTION_ASSIGNMENT`. Exercise is a separate event, not a Boolean variation of an ordinary option trade. `OPTION_ASSIGNMENT` is represented explicitly but remains unsupported and fails closed.
5. **`IndiaOptionType`** enum: `CALL`, `PUT`.
6. **`IndiaRecoveryTaxTreatment`** enum: `EXCLUDE_AS_QUALIFIED_PURE_AGENT`, `INCLUDE_IN_TAXABLE_VALUE`. Missing treatment makes a complete GST result unavailable.
7. **`IndiaChargeIncidence`** enum: `CLIENT_PASSTHROUGH`, `BROKER_ABSORBED`, `NOT_APPLICABLE`.
8. **`IndiaChargePassThroughPolicy`** frozen dataclass: explicit incidence for each of `stt`, `stamp_duty`, `exchange_txn`, `ipft`, and `sebi_turnover_fee`, plus `version` and `source_ref`. Every component is classified; no implicit pass-through default. `NOT_APPLICABLE` is valid only with an explicit zero rule. The returned `ChargeBreakdown` represents modeled client cost: `BROKER_ABSORBED` components contribute zero to the client total but retain an incidence/source note in provenance. This policy describes modeled client cost, not the legal payer of a member-level fee.
9. **`IndiaChargeCalculationContext`** frozen dataclass extending `ChargeCalculationContext`. Because the parent has a defaulted currency field, added fields may default to `None` but must be validated in `__post_init__`:
   - `exchange: IndianExchange | None = None` — required by validation; only NSE is supported.
   - `trade_side: IndiaTradeSide | None = None`, `product: IndiaChargeProduct | None = None`, `event: IndiaChargeEvent = TRADE`, and `effective_at: datetime | None = None` — required fields are validated before calculation.
   - `premium_value: Decimal | None = None` — required for ordinary equity-option trades; never inferred silently from underlying notional.
   - `option_type: IndiaOptionType | None`, underlying-unit `quantity: Decimal | None`, `settlement_price: Decimal | None`, `strike: Decimal | None`, and `exercise_notional_value: Decimal | None` — required as applicable to `OPTION_EXERCISE`. `exercise_notional_value` is the separate SEBI turnover basis, not STT intrinsic value. For this event, the represented party is the exercising purchaser (`trade_side=BUY`); other values are rejected.
   - `brokerage: Decimal | None = None`, `dp_charges: Decimal | None = None`, `other_taxable_service_charges: Decimal | None = None` — required for complete GST; explicit `Decimal('0')` means known zero/not applicable, `None` means unknown. These caller-supplied amounts are also represented as breakdown components so `ChargeBreakdown.total` includes them; `other_taxable_service_charges` excludes amounts already represented by brokerage and DP to prevent double counting. The India schedule does not calculate their tariff.
   - `stt_gst_treatment: IndiaRecoveryTaxTreatment | None`, `stamp_duty_gst_treatment: IndiaRecoveryTaxTreatment | None`, `pass_through_policy: IndiaChargePassThroughPolicy | None`, `gst_policy_version: str | None`, and `gst_policy_source_ref: str | None` — required for a complete client-side result; none has an implicit default.
10. **`IndiaChargeRateSet`** frozen dataclass: Decimal-or-None rates per component (`stt_rate`, `stamp_duty_rate`, `exchange_txn_rate`, `ipft_rate`, `sebi_turnover_rate`, `gst_rate`) plus immutable sorted `component_sources: tuple[tuple[str, str, str], ...]` containing `(component_name, source_ref, rule_version)`. Rates are fractional multipliers: 0.1% is `Decimal('0.001')`, not `Decimal('0.1')`. Every component, including zero, requires source/applicability provenance. `None` means missing/unsupported and rejects the complete calculation; `Decimal('0')` means a sourced zero or explicit client-side non-liability.
11. **`IndiaChargeScheduleEntry`** frozen dataclass: `effective_from: datetime` and `effective_to: datetime | None` (exclusive; `None` means open-ended). Both boundaries must be timezone-aware `Asia/Kolkata` midnight instants, and `effective_from < effective_to` when `effective_to` is supplied. It has a non-empty `version` and `rates` stored as an immutable, sorted tuple of `((IndiaChargeProduct, IndiaTradeSide, IndiaChargeEvent), IndiaChargeRateSet)` pairs with unique keys. Validate/normalize the tuple at construction; do not retain a caller-owned mutable mapping inside a frozen dataclass. Do not use one entry-level source reference for all components.
12. **`IndiaChargeSchedule`** frozen dataclass: immutable, sorted tuple of entries. `select(effective_at)` requires a timezone-aware datetime, normalizes it to `Asia/Kolkata`, and returns the uniquely covering entry or raises `IndiaChargeRuleUnavailable`; gaps may represent explicit unsupported history.
13. **`IndiaMarketChargeModel`** implementing the existing `ChargeModel`:
   - `model_id = india.market_charges`; `model_version = '1'` is the stable calculator/schema version, not the selected tariff version.
   - `calculate(context)` validates exchange is NSE, currency is INR, Decimal inputs are finite and in range, timestamps are aware, and event-specific inputs are present before computing anything.
   - Select rules by effective instant normalized against Asia/Kolkata market-time boundaries, then by `(product, side, event)`. Any missing component rule/source, unsupported scope or required input raises; no partial or zero-substituted breakdown is returned.
   - Use premium value for ordinary option components whose source basis is premium; transaction value for equity/futures; CALL/PUT intrinsic value for exercise STT; and separate `exercise_notional_value` for exercise SEBI turnover. Other event-specific component bases/rates must be sourced or unavailable.
   - Stamp duty is charged to the modeled client only on BUY. SELL-side non-liability is an explicit zero rule with provenance. Exchange/IPFT/SEBI components enter modeled client cost only according to the required caller pass-through policy.
   - GST uses the explicit taxable-base treatment and complete caller-supplied billing inputs in §2.5; missing inputs, treatment or a sourced effective-dated GST rule raises.
   - `ChargeBreakdown.components` includes STT, stamp duty, exchange transaction, IPFT, SEBI fee, GST, and caller-supplied brokerage/DP/other-taxable-service amounts. It includes only client-applicable amounts according to pass-through policy; caller-supplied fees are marked as such.
   - `ChargeBreakdown.provenance` identifies schedule version/interval, every component source/version, and pass-through/tax-policy references.
14. **`IndiaChargeRuleUnavailable`** — stable `ValueError` subtype for missing schedule/component rule/source or unsupported exchange/product/date/event.
15. **`IndiaChargeInputUnavailable`** — stable `ValueError` subtype for missing or incomplete event/billing/tax/pass-through inputs. Do not expose arbitrary supplied values or exception text.

### 5.2 Date selection and unsupported scope

- `effective_at` must be timezone-aware. Normalize the supplied instant to Asia/Kolkata before selection. Schedule boundaries are timezone-aware midnight instants in Asia/Kolkata, representing effective local dates; equivalent UTC/IST instants must select the same rule.
- Inclusive/exclusive: `effective_from <= normalized_effective_at < effective_to` (`effective_from` inclusive, `effective_to` exclusive). An entry with `effective_to = None` is open-ended.
- Reject overlapping ranges. Gaps are explicit unsupported intervals: selection within a gap raises `IndiaChargeRuleUnavailable`; do not force unresolved history into invented rates.
- Schedule construction validates sorted boundaries, timezone awareness, non-empty versions, complete component mappings, source coverage, rate finiteness and non-negativity.
- Unsupported scope (fail closed, never silently fall back): BSE, MCX, NCDEX; currency/commodity derivatives; fund units and special-offer products until explicit categories/sources are reviewed; dates before the earliest fully supported entry, including pre-October-2024 slab-wise exchange charges; any absent product/side/event combination; `OPTION_ASSIGNMENT` (unsupported in this first slice); and an exercise missing option type, quantity, settlement price, strike or SEBI exercise-notional value.
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

`ports/charges.py` owns the neutral `ChargeModel`, `ChargeBreakdown`, `ChargeComponent` and `ChargeCalculationContext` contracts. `execution/charges.py` re-exports those same objects for compatibility and retains `PercentageBpsChargeModel`; the India module imports directly from `ports.charges`. No India-specific tariff or rule is added to the neutral port layer.

The first implementation slice is the contract plus synthetic test schedules only. No unverified production rates are embedded as defaults. A caller must explicitly select the India model; a missing India rule never falls back silently to a generic percentage model.

### 5.6 Calculation and rounding policy

- **Monetary base:** per trade/fill; each component uses its own source-defined basis.
- Equity delivery/intraday/futures use source-defined traded value. Ordinary equity options use premium traded wherever the source prescribes premium.
- **Option exercise:** STT uses intrinsic value (CALL: `max(settlement_price - strike, 0) x quantity`; PUT: `max(strike - settlement_price, 0) x quantity`). SEBI turnover fee uses separately supplied, rule-defined exercise notional. Missing either basis fails closed.
- All intermediate values are finite `Decimal`; no floats. Source rates are converted once to documented fractional multipliers.
- Rounding mode: `ROUND_HALF_UP` to paise per component per trade. Total is the sum of rounded component amounts, not a re-rounding of the unrounded aggregate. This is a QuantX simulation convention, not a verified exchange/statutory rule; an authoritative rule overrides it.
- **GST:** calculate only with complete explicit billing inputs, pass-through policy, and STT/stamp recovery treatments. Qualified pure-agent exclusions apply only when the caller establishes the relevant conditions.
- **Pass-through:** every member-level exchange/IPFT/SEBI fee is explicitly classified as client-pass-through, broker-absorbed or not applicable; no retail-client billing behavior is inferred from a member-outflow circular.
- **Aggregation:** the India charge calculator in this issue is per trade/fill. Client/security/settlement-day clearing aggregation is outside this calculator and is deferred; do not approximate it by applying ordinary per-trade rounding to settlement obligations.

## 6. Implementation sequence

1. **Research/design** — retain the primary-source inventory, rate/effective-date questions and per-trade contract specification in this document.
2. **Per-trade India charge contract + T21 synthetic tests — implemented.** The India calculator and tests live at `src/quantx/markets/india/charges.py` and `tests/unit/markets/india/test_charges.py`. Synthetic fixtures establish calculator behavior, not production tariff approval.
3. **Production schedule — future slice.** Activate only rates with complete authoritative source, publication/effective-date, product/segment/side, calculation-basis and worked-example evidence. Preserve UNKNOWN for the 30 March / 1 April 2026 legal commencement boundary until resolved by a competent authority.
4. **Broker reconciliation and paper/research integration — future slice.** Compare calculated estimates with authoritative broker contract notes/charge records, model only evidenced client incidence, then integrate through the existing charge port. No production broker call or LIVE action is part of this issue.
5. **Physical-delivery settlement — explicitly deferred.** The research register in §8 is non-blocking and supplies no implementation requirement for this issue.

Do not bundle production schedule/loader, broker-specific assumptions, clearing-report ingestion, physical-settlement tax calculations or execution wiring into the contract-only slice. `execution/charges.py` remains an identity-preserving compatibility facade for neutral charge contracts and retains the generic percentage model; do not add India tariff or accounting/risk behavior there.

## 7. Acceptance matrix — per-trade charges

**Test-fixture rule:** T1–T21 and the new physical-settlement stamp-duty contract tests use synthetic fixtures where necessary; they do not prove tariff approval or clearing-feed correctness. Physical-stamp tests use synthetic rates, price and obligation sources. No production schedule or clearing reconciliation claim is implied.

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
| T21 | Schedule-selection boundary before/at Mar 1, 2026 00:00 IST for cash delivery/intraday, futures and options premium, BUY and SELL | Implemented in follow-up branch and operator-reported PASS at exact SHA `ca0ceb606c867c3f98309223e9c7a170b42deb9b`: eight cases verify component splits and preserved published per-side member-fee totals. Pass-through is explicit and synthetic only; not universal broker billing policy. |
| T23 | Brokerage, DP, other-taxable-service amount, pass-through policy or GST treatment missing | `IndiaChargeInputUnavailable`; no supposedly complete GST amount |
| T24 | GST treatment excludes STT/stamp only with a supplied qualified-pure-agent decision | Base follows explicit policy; absent policy refuses; test exclusion and inclusion paths |
| T25 | Same underlying trade with client BUY vs SELL | Stamp duty charged only on client BUY; SELL has explicit source-backed zero for client liability |
| T26 | Exchange BSE/MCX/NCDEX or missing exchange | `IndiaChargeRuleUnavailable` before returning any component |
| T27 | CALL and PUT exercises with positive/negative/zero raw intrinsic differences | Intrinsic value uses correct direction and is never negative |
| T28 | Exercise STT basis vs SEBI basis | STT uses intrinsic value; SEBI uses exercise notional; one cannot substitute for the other |
| T29 | Missing client fee-incidence/pass-through classification | `IndiaChargeInputUnavailable`; no assumed retail pass-through |
| T30 | Model identity vs tariff identity | `model_version` remains implementation version; selected schedule version and component sources are in provenance |
| T31 | A component is `BROKER_ABSORBED` | Client-facing amount is zero, it is excluded from client GST base, and evidence of the underlying component/source plus incidence remains in provenance |
| T32 | `OPTION_ASSIGNMENT` event in first-slice model | `IndiaChargeRuleUnavailable`; cannot be treated as an ordinary trade or `OPTION_EXERCISE` without separate sourced rules |
| T33 | Attempt to mutate the caller's original rates mapping after schedule-entry construction | Schedule selection/results remain unchanged because the entry owns an immutable validated representation |

The former Sunday-dated T2/T5 examples are changed to real trading dates. T17/T18/T21 are schedule-selection boundary tests, not simulated executions on a non-trading session.

## 8. Deferred physical-settlement research — not Issue #200 acceptance criteria

The following records preserve prior source analysis for a possible later stock-F&O physical-delivery capability. They are **not implementation requirements, acceptance tests, or blockers** for Issue #200. The current issue deliberately does not implement a State/UT domicile engine, client/security/day obligation aggregation, physical-delivery STT or stamp-duty calculators, clearing-file ingestion, F_SD03/F_SD04 reconciliation, settlement-price derivation, or corrections/auction workflows.

Revisit this work only if QuantX explicitly decides to support carrying stock derivatives through physical delivery and the feature has a concrete product/risk requirement. Until then, unsupported delivery exposure must be controlled by the strategy/expiry risk boundary; do not build a parallel clearing back office.

The T22 and T34–T46 identifiers are retained to preserve links to the previous research register. They are not part of the per-trade acceptance matrix above.

| Reference | Deferred research/guard | Future evidence required |
|---|---|---|
| T22 | Physical-settlement stamp-duty treatment | A complete production schedule for physically settled stock derivatives is rejected until the separate underlying-delivery stamp-duty treatment is sourced. Standard Article 56A derivative rates are supported; do not infer an extra 0.015% or silently assume none. |
| T34 | Physical settlement of NSE stock futures and options | Apply additional delivery-based equity STT (0.10% as source-verified for the current regime) separately from ordinary derivative trade STT and option-exercise STT; both purchaser/receiver and seller/giver are liable. Require authoritative delivery-settlement value and explicit receiver/giver role; never infer role from the original derivative trade BUY/SELL side. The current contract lacks this event and input set. |
| T35 | Physical-settlement stamp-duty calculation | At one client/security/settlement-day group, aggregate all eligible equity-futures/options security-receivable positions as BQTY and security-deliverable positions as SQTY. Compute BDQTY=max(BQTY−SQTY,0) and BNDQTY=min(BQTY,SQTY); value at sourced final settlement price; apply injected delivery/non-delivery rates separately; round each component to paise; then round client total to nearest rupee (50 paise up). The synthetic calculation contract and tests passed operator-reported exact-SHA validation at code-only candidate `5fcb69920a25050e4eb5e7d72991af7fdf5f4867`. It does not ingest clearing files, use production rates, calculate final price or physical STT; F&O physical duty stays separate from Capital Market transaction duty. |
| T36 | SEBI fee effective-date/source transition at January 7, 2026 | Use P8 for the historical 1992-regulation period and P9 from January 7, 2026; retain ₹10/crore equity-derivatives rate and premium-plus-exercise/assignment-notional option turnover basis. Assignment remains unsupported by the current India calculator. |
| T37 | GST stock-broking classification and rate | Confirm SAC 997152 / Heading 9971 and 9% CGST + 9% SGST (or 18% IGST) from July 1, 2017; test taxable-base inclusion/exclusion independently under the explicit caller policy and Rule 33 conditions. |
| T38 | Current-version clearing rule verification | P13 NCL/CMPT/73997 Part B Items 6/21 and its Part E UDiFF format are reported downloaded and inspected. The operator reports the physical-STT delivery leg, stamp-duty aggregation, rounding and report names; the cross-version document acquisition gate is complete. Row-level FOPHY STT/Obligation/StampDuty joins, actual member samples and the combined exercise/delivery STT amount remain UNKNOWN. |
| T39 | Physical-settlement stamp-duty jurisdiction and rounding | Resolve client State/UT from the client code; use trading-member State/UT only when client State/UT is unavailable. Preserve the resolution source. Sikkim means NCL does not collect the duty; do not convert this into a legal zero rate. Verify separate paise component and nearest-rupee client rounding. |
| T40 | Physical-settlement jurisdiction resolution | Resolve client State/UT from the client code placed/modified within the permitted client-code window. For proprietary transactions, the trading-member code is the client code. If client State/UT is unavailable, use the Trading Member's State/UT as the prescribed fallback and record which path resolved it. Missing both is unsupported. For Sikkim, represent NCL no-collection separately from calculated duty/rate; never silently return zero as if no duty were legally due. |
| T41 | Cross-segment physical-obligation netting vs stamp-duty computation | Where the same security has common CM/TM/client UCC across F&O and Capital Market, settlement obligations may be netted; when clearing member/CC differs, they are not. In either case, calculate F&O physical stamp duty and Capital Market transaction stamp duty separately. |
| T42 | Effective-dated final-settlement-price provenance | Require official final settlement price, security, expiry/settlement date, source/version and applicable methodology. P15 Annexure A is reported inspected: stock settlement uses the stated CTS 15:00–15:30 branch rules; the no-last-30-minute-trade reference (“point 1 and 2”), scenario-3 rounding, §2.2.2 index method mapping, and unusual-event handling are unresolved. P14's December 7, 2026 transition remains effective-dated; no fallback is inferred. |
| T43 | Settlement-role mapping for physical STT | Use clearing-obligation semantics from P12 Item 5.4.1: long futures and long exercised calls are security-receivable; short futures and short assigned calls are security-deliverable; long exercised puts are security-deliverable; short assigned puts are security-receivable. Quantity is market lot × contracts. Apply physical STT to both receiver and giver; physical stamp duty is receiver-side. A raw derivative BUY/SELL side is not a substitute for the settlement-role result. |
| T44 | Clearing report reconciliation | Reconcile client-level physical stamp duty and its TM/CM roll-ups with NCL F_SD03 (TM delivery-settlement stamp-duty file) and F_SD04 (CM delivery-settlement stamp-duty file). Do not claim production calculation fidelity until report schema, source lineage and lawful sample evidence are available. |
| T45 | Physical-settlement STT separation | The stamp-duty-only candidate must not calculate physical-settlement STT or claim a complete all-in result. Physical STT is a separate 0.10% event for receiver and giver; exact settlement-value basis and authoritative input schema remain to be resolved before implementation. |
| T46 | Physical-settlement BQTY/SQTY completeness boundary | Require one pre-aggregated group per client/security/settlement day, covering all clearing-recognized futures/options security-receivable and security-deliverable positions. Reject duplicate security groups in one context; do not infer completeness or assignments from local Position rows. |

## 9. Out of scope (do not implement in this slice)

- Physical-delivery F&O clearing/tax subsystem: State/UT resolver, NCL file ingestion, physical STT/stamp-duty calculators, settlement-price logic, reconciliation and correction/auction workflows.
- New accounting engine or replacing `execution/charges.py`.
- Hardcoding unverified rates in production code.
- Brokerage, DP charges (broker-specific).
- BSE/MCX/NCDEX charge schedules.
- Currency/commodity derivatives, fund units and special-offer products until explicit product categories and primary-source schedules are added.
- SEBI compliance layer (separate scope).
- LIVE broker receipt charges (separate slice, needs authoritative broker evidence).
- #267 (risk-evidence authority) and #266 (daily-loss semantics) — tracked separately.

---

## 10. Unresolved questions

1. Who owns and validates the caller-supplied GST/billing policy, including pure-agent treatment and the components billed to the client? This is an explicit input contract, not a legal determination by QuantX.
2. Should schedule data be loaded from a Python module or versioned JSON/YAML? (Proposed: Python module, consistent with `markets/india/rule_data.py`.)
3. Keep IPFT separate for auditability, even though it participates in the published NSE member outflow.
4. BSE support remains separate scope; NSE first.
5. Pre-Oct-1-2024 slab-wise exchange charges remain unsupported until a separate volume-tiered design is justified.
6. Which authoritative consolidated stamp-duty source and GST rate notification will close the production data gates in §4? Until resolved, those production entries remain unavailable.
7. Confirm that the caller's pass-through policy represents client economic incidence while source provenance separately records the legal fee payer/member outflow.

---

## 11. Evidence status

- **Structural inspection:** `execution/charges.py`, `india/execution_rules.py`,
  `markets/india/rule_data.py`, `india/domain.py`, `research/provenance.py`,
  `research/point_in_time.py`, `tests/unit/execution/test_charges.py`,
  `docs/architecture/52-transaction-cost-and-charges.md` — all read.
- **Per-trade runtime/test evidence:** T1–T21 and T23–T33 plus the T21 follow-up were historically validated by the operator on earlier exact candidates. Those reports are historical and do not replace exact-head validation of the current-main PR candidate. The physical-settlement experiment had a separate historical validation report, but that code/tests are now excluded from this issue and no such result is an acceptance claim for Issue #200. No GitHub Actions or paid CI is used or claimed.
- **Source research:** P1–P15 primary-source retrieval is complete per the operator's 10–11 November reports, including P13 Item 6/21, P15 Annexure A, predecessors 73370/76951 and BSE 20261030-51 Annexure A. The report records source hashes and page-by-page review; this workspace has not independently opened all binary attachments. UDiFF Annexure B/C schemas and samples are reported audited, with field definition alignment but low/medium-confidence join candidates and unresolved sample anomaly. P15 fallback wording and statutory/tax interpretations remain open. S1–S5 are cross-checks/administrative guidance; S6 is the official UDiFF page and attachments.
- **Status boundary:** the current scope is the source-labelled, caller-configured per-trade India charge contract; no production defaults or execution integration exist. Operator reports P13/P15 retrieval/inspection complete, but the local source bundle has not been independently authenticated here. For Issue #200, production activation blockers are statutory/effective-date interpretation, applicable per-trade rate schedules, billing/pass-through policy evidence and authoritative ordinary-trade worked examples. Physical-delivery taxable-value mapping, FOPHY clearing joins, State/UT resolution, P15 settlement-price methodology, corrections/shortage/auction and physical-delivery worked examples remain preserved as deferred research, not blockers for this issue.
- **Non-claims:** this source review does not create a production tariff loader, prove broker-specific pass-through, or authorize any paper/research/live execution integration. Rates and bases marked UNRESOLVED remain unavailable to production calculation.
