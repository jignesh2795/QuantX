# ADR 0059: Dhan Whole-Account Position Evidence — C2b Blocked

**Status:** BLOCKED. No Dhan source can currently establish a complete, marked, whole-account position book.
**Base:** `261ab0904f722a82861a2ecb3add78742969e123`
**Implementation branch:** `feat/slice-c2b-whole-account-position-evidence-v1`
**Validation:** Exact-SHA local validation is recorded in `docs/STATUS.md`. This ADR claims no test result.

## Context

Slice C1 added `WholeAccountPositionEvidence` and `build_live_risk_inputs`, which
reject any position book that is not `COMPLETE` with `POSITIONS`, `HOLDINGS`,
and `MARKS` surfaces and canonical `LivePositionEvidence` rows. C2b must supply
that book from a real provider, or explicitly record why the provider cannot.

The C2b contract additionally requires canonical instrument and product
identity, signed quantities, a cost basis, usable marks with a defensible
observation time, and a declared cross-surface merge policy. The Dhan
integration is pinned to `dhanhq==2.2.0`; the provider contract was checked
against the current official DhanHQ v2 documentation and the pinned SDK
implementation. Method names and field presence alone were not treated as
evidence of completeness.

## Verified provider semantics

### Positions — `GET /positions`

The official documentation states: "Users can retrieve a list of all open
positions for the day. This includes all F&O carryforward positions as well."

Each row exposes `securityId`, `exchangeSegment`, `tradingSymbol`, `productType`,
`positionType` (`LONG`, `SHORT`, `CLOSED`), `netQty`, `buyQty`, `sellQty`,
`buyAvg`, `sellAvg`, `costPrice`, `realizedProfit`, `unrealizedProfit`,
`multiplier`, carry-forward and day quantities/values, `rbiReferenceRate`,
`crossCurrency`, and derivative metadata.

What this does not establish:

- There is no book-level observation timestamp, row count, completeness marker,
  pagination contract, or documented statement that the list is a point-in-time
  snapshot of the whole account.
- The endpoint is defined as the **day's open-position** surface. It is not
  documented as a complete exposure book covering settled delivery holdings.
- `positionType` and `netQty` are not documented as a cross-checked pair. A
  `LONG` row with negative `netQty` (or vice versa) has no verified meaning, so
  the source cannot choose one field as authoritative.
- `costPrice` has no documented derivation: it is not stated whether it is the
  opening basis, the mark-to-market basis, or a blended value across
  carry-forward and day trades. `buyAvg`/`sellAvg` cannot repair that gap.
- `multiplier` is documented as "multiplying factor for currency F&O"; it is not
  a general contract multiplier authority for equity derivatives.
- `drvExpiryDate` uses `"0001-01-01"` as its non-derivative sentinel, and
  `drvOptionType`/`drvStrikePrice` have their own sentinels. These sentinels are
  not documented as a single, reliable "not a derivative" marker.
- `productType` is a wire enumeration (`CNC`, `INTRADAY`, `MARGIN`, `MTF`, `CO`,
  `BO`). Mapping it to a canonical `ProductCode` requires an explicit,
  unambiguous configuration; the provider gives no neutral identity and no
  guarantee that one wire value maps to one neutral product.

### Holdings — `GET /holdings`

The official documentation states: "Users can retrieve all holdings bought/sold
in previous trading sessions. All T1 and delivered quantities can be fetched."

Each row exposes `exchange`, `tradingSymbol`, `securityId`, `isin`, `totalQty`,
`dpQty`, `t1Qty`, `availableQty`, `collateralQty`, and `avgCostPrice`. The
documented example uses `"exchange": "ALL"`.

What this does not establish:

- There is no product type at all. A holding is not documented as `CNC`,
  delivery, margin, MTF, or any other canonical product. Assigning one would be
  invented identity.
- There is no observation timestamp, row count, or completeness marker.
- The exposure quantity basis is undefined. `totalQty` is "Total quantity",
  `availableQty` is "Quantity available for transaction", and `collateralQty`
  is "Quantity placed as collateral with broker"; the documentation does not
  state which of these represents risk exposure, whether collateralized
  quantity remains an exposure, or whether `totalQty` can exceed the sum of
  `dpQty` and `t1Qty`.
- `exchange: "ALL"` has no documented row-level exchange-segment identity, and
  the same `securityId` can exist on more than one venue. Segment attribution
  is therefore not proven.
- The endpoint is defined as previous-session, T1, and delivered demat
  quantity. It is not documented as today's full exposure book.
- `avgCostPrice` is "Average Buy Price of total quantity"; its relationship to a
  settled or unsettled basis, and its behavior for collateral or pledged
  quantity, is not defined.

### Cross-surface overlap — `/positions` versus `/holdings`

The provider documentation does not state whether a `CNC` position row and a
holding row for the same instrument are:

- independent exposures that must be added,
- the same exposure reported twice, or
- mutually exclusive settlement states.

There is also no documented rule for the transition window between an executed
delivery trade and its appearance in holdings. Without that rule, any merge is
an assumption: summing double-counts, and choosing one surface under-counts.
C2b requires an explicit merge policy, and no provider-endorsed policy exists.

### Marks — `POST /marketfeed/quote` and `POST /marketfeed/ltp`

Dhan's Data APIs are a **separately purchased subscription**. Dhan's support
documentation states the Data API subscription is "available at ₹499 +
applicable taxes per month" and is auto-debited from the trading ledger every
30 days. Trading API access does not imply market-data entitlement, and this
change does not assume, purchase, or probe that entitlement.

The quote response also does not provide a server-side observation timestamp.
`last_trade_time` is documented as a string whose description is the copy-paste
error "Last traded quantity"; the response example is
`"01/01/1980 00:00:00"`, a sentinel rather than a real trade. No date format,
timezone, or sentinel rule is documented, so the field cannot be treated as a
verified trade instant.

Consequences for C2b:

- The only trustworthy observation instant on a quote is the local read
  instant, which is **not** provider authority for mark freshness.
- A mark whose trade time is missing or sentinel cannot be distinguished from a
  stale or never-traded instrument.
- Querying a quote without an entitlement would produce an error response, not
  evidence; querying one and labeling the local clock as the mark time would
  fabricate freshness.

### SDK 2.2.0

The pinned SDK calls `get_positions()` → `GET /positions`, `get_holdings()` →
`GET /holdings`, and `MarketFeed(...).quote_data(...)` → `POST /marketfeed/quote`.
It adds an HTTP envelope, but no timestamps, completeness metadata, product
identity, overlap policy, or mark-time normalization. The SDK adds no authority
that the documented endpoints lack.

## Decision

C2b is **BLOCKED** for Dhan. The verified provider contract cannot establish a
complete, marked, whole-account position book.

The implementation adds `DhanWholeAccountPositionSource`, reachable as
`DhanBrokerAdapter.whole_account_position_evidence(...)`. It:

- reads `/positions` and `/holdings` read-only to build an **auditable refusal**
  (row counts and every semantic gap are recorded);
- never emits a canonical `LivePositionEvidence` row, because no authorized mark
  surface exists and unmarked positions must not enter the risk book;
- never returns `COMPLETE`; the best case is `INCOMPLETE`, and a total read
  failure is `UNAVAILABLE`;
- declares `merge_policy="dhan-no-cross-surface-merge-fail-closed-v1"` and
  `MARKS` status `UNAVAILABLE`;
- names each reason in `WholeAccountPositionEvidence.blockers`, including the
  static provider gaps and any observed row-level inconsistency.

The blocker codes are stable, auditable strings:

| Blocker | Meaning |
| --- | --- |
| `DHAN_POSITIONS_PROVIDER_TIMESTAMP_UNAVAILABLE` | `/positions` supplies no book timestamp |
| `DHAN_POSITIONS_SCOPE_UNPROVEN` | day's open positions (plus F&O carry-forward) are not a complete exposure book |
| `DHAN_HOLDINGS_PROVIDER_TIMESTAMP_UNAVAILABLE` | `/holdings` supplies no book timestamp |
| `DHAN_HOLDINGS_SCOPE_UNPROVEN` | previous-session/T1/delivered demat quantity is not today's complete exposure book |
| `DHAN_HOLDINGS_PRODUCT_IDENTITY_UNPROVEN` | holdings carry no product, and none is invented |
| `DHAN_HOLDINGS_EXPOSURE_QUANTITY_UNPROVEN` | `totalQty`/`availableQty`/`collateralQty` exposure basis undefined |
| `DHAN_CROSS_SURFACE_OVERLAP_POLICY_UNPROVEN` | no documented positions/holdings merge rule |
| `DHAN_MARK_AUTHORITY_UNAVAILABLE` | no entitled, authorized mark surface in C2b |
| `DHAN_MARK_TRADE_TIMESTAMP_UNVERIFIED` | quote trade time has no verified format/sentinel contract |
| `DHAN_TRANSPORT_NOT_CONFIGURED` | no read transport was supplied |
| `DHAN_POSITION_PRODUCT_MAP_UNAVAILABLE` | no explicit wire-to-neutral product map |
| `DHAN_POSITION_PRODUCT_MAP_AMBIGUOUS` | two neutral products share one wire value |
| `DHAN_POSITIONS_UNAVAILABLE` / `DHAN_HOLDINGS_UNAVAILABLE` | read failed or response was malformed |
| `DHAN_POSITION_INSTRUMENT_UNMAPPED` / `DHAN_HOLDING_INSTRUMENT_UNMAPPED` | row has no canonical instrument mapping |
| `DHAN_HOLDING_INSTRUMENT_AMBIGUOUS` | `exchange: ALL` row matches multiple venue-segment mappings |
| `DHAN_HOLDING_EXCHANGE_UNSUPPORTED` | holdings exchange value outside the supported set |
| `DHAN_POSITION_DUPLICATE_ROW` / `DHAN_HOLDING_DUPLICATE_ROW` | duplicate rows; never silently summed |
| `DHAN_POSITION_PRODUCT_MISSING` / `DHAN_POSITION_PRODUCT_UNMAPPED` | row product absent or not in the configured map |
| `DHAN_POSITION_TYPE_UNPROVEN` | `positionType` missing or outside `LONG`/`SHORT`/`CLOSED` |
| `DHAN_POSITION_TYPE_QUANTITY_INCONSISTENT` | sign and `positionType` contradict each other |
| `DHAN_POSITION_COST_BASIS_UNAVAILABLE` | cost basis missing or non-positive |
| `DHAN_POSITION_MULTIPLIER_INCONSISTENT` | provider multiplier contradicts the canonical instrument |
| `DHAN_POSITION_CURRENCY_UNSUPPORTED` / `DHAN_POSITION_SEGMENT_UNSUPPORTED` | out-of-scope currency or segment |
| `DHAN_POSITION_CROSS_CURRENCY_UNSUPPORTED` | provider flags a non-INR currency pair |
| `DHAN_DERIVATIVE_QUANTITY_BASIS_UNPROVEN` | derivative quantity unit/multiplier basis is not established |
| `DHAN_HOLDING_QUANTITY_UNAVAILABLE` / `DHAN_HOLDING_COST_BASIS_UNAVAILABLE` | row quantity or cost basis missing/non-positive |
| `DHAN_HOLDING_CURRENCY_UNSUPPORTED` | out-of-scope holding currency |
| `DHAN_HOLDING_COLLATERAL_SEMANTICS_UNPROVEN` / `DHAN_HOLDING_T1_SETTLEMENT_SEMANTICS_UNPROVEN` | collateral or T1 exposure meaning undefined |
| `DHAN_SURFACE_OBSERVATION_FUTURE_DATED` / `DHAN_SURFACE_OBSERVATION_SKEW_EXCEEDED` | surface observation time is implausible relative to the caller's instant |
| `DHAN_CROSS_SURFACE_OVERLAP` | same instrument observed on both surfaces; disposition unknown |

`DhanHoldingSnapshot` deliberately has no product field and the source has no
`holdings_product` override. There is no symbol-, asset-class-, or
default-derived product inference anywhere. Product identity can only come from
an explicitly configured neutral-to-wire map; for holdings there is no
trustworthy wire value to map.

`WholeAccountPositionEvidence` now requires any `COMPLETE` book to carry an
empty `blockers` tuple, and `build_live_risk_inputs` independently rejects a
book that declares blockers with `LIVE_RISK_POSITION_BOOK_INCOMPLETE`. The
second check is defense in depth: it must hold even if a caller constructs or
mutates a book outside the domain constructor.

The quote model fix is part of the same provider-semantic audit:
`DhanQuoteSnapshot.observed_at` is explicitly the local read instant, and
`trade_observed_at` is populated only for an unambiguous ISO or epoch trade
time. The documented 1980 sentinel, missing values, and unknown formats remain
`None`; the local clock is never substituted for provider trade time.

## Required future authority

C2b can only be unblocked by a provider-endorsed contract that supplies all of:

- a complete whole-account exposure book with an authoritative observation time
  and a completeness/pagination guarantee;
- canonical instrument identity, venue/segment identity, and product identity
  on every exposure row;
- a defined exposure-quantity basis, including collateral, pledged, T1, and
  carry-forward treatment;
- a documented rule for positions/holdings overlap and settlement transitions;
- a mark surface with provider or exchange timestamps that can be verified
  against the book's observation time;
- explicit currency and multiplier semantics for every supported product.

A complete broker portfolio snapshot (positions and holdings in one atomic
payload with product and timestamps) plus a timestamped, entitled quote feed
would qualify. Independent endpoint combinations do not.

## Non-claims

- No Dhan broker I/O, credentials, orders, or LIVE trading occurred.
- No Data API subscription was purchased, probed, or assumed; C2b performs no
  mark query.
- No sanctioned LIVE stack is enabled; `build_live_execution` continues to
  refuse production LIVE composition.
- No Dhan data is treated as authoritative by this ADR.
- C2a remains `BLOCKED`; its `DhanRealizedDailyPnlSource` still returns
  `UNAVAILABLE` with `amount=None` and no daily charges. No realized P&L is
  derived from positions.
- C2c margin/currency authority, C2d pending-scope persistence, C2e concurrency
  leases, and approval-binding orchestration remain out of scope.
- A C2b unblock, even if achieved later, would not by itself establish LIVE
  readiness.
- No test command or test result is claimed by this ADR.
