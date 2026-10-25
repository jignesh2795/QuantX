# ADR 0058: Dhan Realized Daily P&L Authority — C2a Blocked

**Status:** BLOCKED. No Dhan source can currently establish complete, whole-account realized daily P&L.
**Base:** `292bd213b5ba6c2ef45954a706f3d841e49813fc`
**Implementation branch:** `feat/slice-c2a-authoritative-daily-pnl-v1`
**Validation:** Exact-SHA local validation is recorded in `docs/STATUS.md`. This ADR claims no test result.

## Context

Slice C1 added the typed `RealizedDailyPnlEvidence` contract and a builder that
rejects any P&L authority that is not `COMPLETE`, `WHOLE_ACCOUNT`, charge-covered,
and bound to the trusted trading day and session start. C2a must supply that
authority from a real provider, or explicitly record why the provider cannot.

The Dhan integration is pinned to `dhanhq==2.2.0`. The provider contract was
checked against the current official DhanHQ v2 documentation and the pinned SDK
2.2.0 implementation; method names alone were not treated as evidence of
completeness.

## Verified provider semantics

### Positions — `GET /positions`

The official documentation describes this endpoint as: "Users can retrieve a
list of all open positions for the day. This includes all F&O carryforward
positions as well."

The response includes a per-position `realizedProfit` field ("Profit or loss
booked") and a `positionType` parameter whose documented values include `LONG`,
`SHORT`, and `CLOSED`. It also includes per-position `buyQty`, `sellQty`,
`costPrice`, carry-forward quantities/values, and `unrealizedProfit`.

What this does not establish:

- The endpoint is defined as the **open-position** surface. A `CLOSED` row is
  not a documented guarantee that every fully closed intraday or delivery
  position for the account is returned.
- There is no account-level realized P&L total, no row count, no completeness
  marker, and no documented statement that the returned rows cover all of the
  day's realized trading activity.
- The response contains no daily charge field. Summing `realizedProfit` would
  therefore omit daily charges and could silently mix gross trading result with
  a net-of-charge requirement.
- An empty list has no documented meaning of "no activity"; it could also mean
  no open positions. It cannot be converted into a zero-P&L day.

### Trade history — `GET /trades/{from-date}/{to-date}/{page}`

The official documentation says the response is paginated and requires a page
number, with `0` as the default. The response body is a bare array of trade
rows. Each row has an `orderId`, `exchangeTradeId`, transaction side, segment,
product, quantity, price, and per-trade charge columns (`sebiTax`, `stt`,
`brokerageCharges`, `serviceTax`, `exchangeTransactionCharges`, `stampDuty`).

What this does not establish:

- There is no documented page size, total row count, `has-next` flag, or
  end-of-data marker. A short or empty page is not documented as proof that
  pagination is complete. Stopping on the first empty page would be an
  unverified assumption.
- There is no `realizedProfit` field and no prior-day opening basis. Computing
  realized P&L from buys and sells would require a verified carry-forward
  position/cost basis, which the trade history does not supply.
- The per-trade charge columns are not a daily charge authority. They do not
  define aggregation across partial fills, order-level versus trade-level
  charges, taxes, or any daily total. Summing them would invent semantics.
- There is no documented duplicate/overlap policy across pages. Without a
  verified total or page boundary contract, duplicate or missing rows cannot
  be ruled out.

### Ledger — `GET /ledger?from-date=...&to-date=...`

The ledger returns `narration`, `voucherdate`, `exchange`, `voucherdesc`,
`vouchernumber`, `debit`, `credit`, and `runbal` (running balance) strings. It
does not expose a structured realized-trading P&L, instrument-level realized
results, or a daily charge total with defined trading semantics. Debit/credit
narration is not a substitute for the C1 P&L contract.

### SDK 2.2.0

The pinned SDK calls these endpoints directly:

- `get_positions()` → `GET /positions`
- `get_trade_history(from_date, to_date, page_number=0)` →
  `GET /trades/{from_date}/{to_date}/{page_number}`
- `ledger_report(from_date, to_date)` → `GET /ledger`

The SDK adds an HTTP envelope around the response but no completeness metadata,
no aggregation, no pagination termination, and no realized-P&L calculation.

## Decision

C2a is **BLOCKED** for Dhan. The provider does not currently expose enough
verified semantics to establish complete, account-wide realized daily P&L with
defined daily charges.

The implementation therefore adds `DhanRealizedDailyPnlSource`, reachable as
`DhanBrokerAdapter.realized_daily_pnl_evidence(...)`. It returns explicit
`UNAVAILABLE` `RealizedDailyPnlEvidence` with:

- `amount=None` and `charges_daily=None` — never a fabricated zero or partial
  sum presented as a daily result;
- `scope="WHOLE_ACCOUNT"` and `source=BROKER_REPORTED` to identify the requested
  authority family, with `completeness=UNAVAILABLE` making the refusal
  explicit;
- account, connection, broker, trading-day, session-start, `as_of`, version,
  and provenance bindings;
- `uncaptured_activity` naming each provider-semantic gap.

The source performs no broker I/O. No Dhan read surface is queried because none
can satisfy the contract; querying one and then refusing would add no authority.

`RealizedDailyPnlEvidence.amount` is now optional **only** for non-`COMPLETE`
evidence. A `COMPLETE` observation still requires a `Money` amount, and
non-`COMPLETE` evidence may not carry an amount or daily charges. The C1 builder
continues to reject every non-`COMPLETE` status before risk evaluation.

## Required future authority

C2a can only be unblocked by a provider-endorsed surface that supplies all of:

- complete whole-account coverage for the requested trading day;
- all realized trading activity, including fully closed positions and any
  carry-forward basis the source claims to support;
- defined daily charge semantics in the same currency;
- a verified pagination or end-of-data mechanism;
- an account/broker identity and authoritative timestamps/provenance.

A complete broker daily P&L statement, or a complete trade book plus a verified
carry-forward basis and charge authority, would qualify. Partial endpoint
combinations do not.

## Non-claims

- No Dhan broker I/O, credentials, orders, or LIVE trading occurred.
- No sanctioned LIVE stack is enabled; `build_live_execution` continues to
  refuse production LIVE composition.
- No Dhan data is treated as authoritative by this ADR.
- C2b position completeness, C2c margin/currency authority, C2d pending-scope
  persistence, C2e concurrency admission, and approval-binding orchestration
  remain out of scope.
- No test command or test result is claimed by this ADR.
