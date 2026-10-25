# ADR 0059: Dhan Whole-Account Position Evidence — C2b Blocked

**Status:** BLOCKED for Dhan. The provider surfaces are not yet sufficient to build the C1 whole-account position evidence contract without assumptions about overlap/product identity and authorized marks.
**Base:** `261ab0904f722a82861a2ecb3add78742969e123`
**Implementation branch:** `feat/slice-c2b-whole-account-position-evidence-v1`
**Validation:** Pending exact-SHA local validation. This ADR claims no test result.

## Context

C1 requires one canonical whole-account book covering `POSITIONS`, `HOLDINGS`, and `MARKS`, with a valid instrument/product identity, signed quantity, average cost, mark price and timestamp, currency, provenance, a documented merge policy, and an explicit completeness proof. A position row is not by itself a whole-account book.

## Verified Dhan provider contracts

### `GET /positions`

The official [Dhan portfolio and positions documentation](https://dhanhq.co/docs/v2/portfolio/) describes this as the list of all open positions for the day, including F&O carry-forward. The documented row includes `securityId`, `exchangeSegment`, `productType`, `positionType`, `netQty`, `costPrice`, day trade quantities/values, realized profit, and unrealized profit.

That surface is useful for open exposure but does not publish a canonical mark price and mark-observation timestamp per row. The presence of `unrealizedProfit` does not prove the mark price and price timestamp required by C1.

### `GET /holdings`

The official documentation describes this as all holdings bought/sold in previous trading sessions, with T1 and delivered quantities available. Rows include `securityId`, `isin`, `totalQty`, `dpQty`, `t1Qty`, `availableQty`, `collateralQty`, and `avgCostPrice`.

This schema does not expose the `productType` carried by position rows. The published contract does not define how a holdings row relates to a same-instrument open position, how overlap should be reconciled, or how quantities subject to collateral/T1 restrictions should map to the C1 product-aware position model. Summing both lists could double-count exposure; choosing one surface without a contract would silently omit an exposure category.

The endpoints return arrays but do not provide an explicit cross-surface completeness proof or merge identifier. An unmapped row must not be dropped or guessed.

### Marks and Data API entitlement

The [Dhan Market Quote API documentation](https://dhanhq.co/docs/v2/market-quote/) places real-time LTP/quote/depth endpoints under Data APIs. The published LTP response includes `last_price` but no per-row observation timestamp. Quote/depth provides additional fields, but the current QuantX adapter does not establish authorized, fresh, timestamped mark coverage for every whole-account row.

Dhan support's [API access page](https://dhan.co/support/platforms/dhanhq-api/how-to-access-dhan-api/) currently lists Data API subscription at ₹499 plus applicable taxes per month. QuantX does not assume that the account has paid for or enabled this entitlement. The absence of a quote or mark remains unavailable evidence, not a reason to fall back to an inferred price.

## Decision

C2b remains **BLOCKED** for Dhan at the verified contract boundary. This is a provider-contract/entitlement blocker, not a claim that the API cannot return useful position or holdings data for ordinary reconciliation.

The branch adds `DhanWholeAccountPositionEvidenceSource` and an adapter method `assess_whole_account_position_evidence(...)`. They return a typed `UNAVAILABLE` capability assessment scoped to the configured account and connection. It is explicitly an assessment, **not** a `WholeAccountPositionEvidence` snapshot. Its `assessed_at` is the local assessment instant, not a fabricated broker-observation timestamp. No broker I/O is performed.

The assessment reports the exact gaps:

- Undefined position/holdings overlap semantics.
- Missing canonical product identity on holdings rows.
- Unproven whole-account instrument mapping coverage.
- Data API entitlement required for the documented mark route.
- Mark timestamp freshness/coverage not proven for all rows.
- Whole-book completeness not proven.

The existing `DhanBrokerAdapter.position_states()` remains a narrower reconciliation interface. It must not be promoted to whole-account C1 LIVE risk evidence. No integration path can treat the assessment as a position book, and `build_live_execution` remains deliberately fail-closed.

## Unblock criteria

C2b may be reconsidered only when the implementation can demonstrate all of:

1. A provider-endorsed distinction/merge rule for open positions and holdings, including product/quantity semantics and collateral/T1 holdings.
2. Explicit mapping of every provider row to a canonical instrument and the appropriate risk product, rejecting unknown rows.
3. A usable authorized mark source with price, source, currency and timestamp for every active exposure, with freshness/future-time validation.
4. A deterministic duplicate/overlap policy that cannot double-count risk.
5. Evidence-backed complete surface coverage and regression tests for unavailable, empty, stale, duplicated, unmapped, and malformed data.
6. Exact-SHA local test, Ruff, strict mypy, diff-check and repository-integrity validation.

## Relationship to C2a and LIVE readiness

C2a remains **BLOCKED** as documented by [ADR 0058](58-dhan-realized-daily-pnl-c2a-blocker.md). C2b does not unblock C2a. C2c margin/currency authority, C2d durable pending-scope lookup, C2e durable concurrency admission, and end-to-end approval-binding enforcement remain separately unresolved.

No production LIVE stack is enabled. No broker credentials, broker I/O, orders or LIVE trading were used.
