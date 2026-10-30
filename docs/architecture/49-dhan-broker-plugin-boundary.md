# Dhan Broker Plugin Boundary

QuantX integrates Dhan through the canonical broker port without exposing the
DhanHQ SDK to the core.

```text
ApprovedExecutionRequest
        |
        v
ExecutionOrchestrator
        |
        v
     BrokerPort
        |
        v
DhanBrokerAdapter
        |
        v
   DhanTransport
      /     \
     /       \
InMemory    DhanSDKTransport
   test            |
                   v
              DhanHQ SDK
```

## Boundary rules

The Dhan SDK is imported only by
`src/quantx/plugins/dhan/transport.py`. Vendor response payloads are mapped
to QuantX `ExecutionReceipt`, `Fill`, and normalized order status values
inside the plugin. The adapter independently enforces its account-scoped
broker connection before submit, cancel, or reconciliation, so direct adapter
use cannot silently route a request to a different connection.

The canonical QuantX `InstrumentId` remains the system identity. A
`DhanInstrumentRef` separately maps it to Dhan's `securityId`,
`exchangeSegment`, trading symbol, and product type.

Credentials are runtime inputs to `DhanSDKTransport` and are not stored in
QuantX domain objects, plugin descriptors, registrations, orders, or receipts.

Dhan's documented regular-order correlation ID is limited to 30 characters.
QuantX client order IDs may be UUID strings longer than that, so the plugin
derives a deterministic 30-character hexadecimal Dhan correlation ID from the
QuantX correlation ID. The original QuantX correlation remains unchanged in
the execution receipt.

## Supported surface in P1.5

The adapter advertises the capabilities implemented by the existing QuantX
broker contract:

- order submission
- order cancellation
- balances (`account_state`, read from the funds endpoint)
- positions (`position_states` / `position_state_for`, read from the positions endpoint)
- market data (snapshot-only adapter described below)

Order replacement is not implemented. The transport additionally exposes
normalized `profile()`, `fund_limits()`, `positions()`, and `holdings()`
observations for application-level evidence collection. Those reads are not a
second broker port, never expose vendor types, and never invent a missing
value: an unavailable or malformed payload is an unavailable observation.

## LIVE risk-evidence source

```text
AccountConnectionRegistry (application-owned, per process)
        |  registered connection -> adapter
        v
DhanBrokerAdapter.build_live_risk_evidence_binding (plugin construction path)
        |  the application derives its catalog from this adapter
        v
LiveRiskEvidenceSourceCatalog -> LiveRiskEvidenceSourceGrant (sealed)
        |
        v
LiveRiskEvidenceAuthority (application-owned)
        |
        v
DhanRiskEvidenceSource -> DhanTransport
                   (profile / fundlimit / positions / holdings)
```

The source is not trusted by its type, its `source_id`, its `supported_fields`
declaration, or the identity values it echoes. Trust is the registered execution
path: the application derives its catalog from the adapter behind the connection
this process registered in `AccountConnectionRegistry`, and the only accepted
construction path is that adapter's own bound method. `LiveExecutionConfig`
accepts neither a source nor a catalog, and `LiveRiskEvidenceSourceCatalog`
cannot be constructed outside the application, so a caller cannot keep a genuine
Dhan submission path while substituting the evidence it reads. A deployment that
registers no Dhan adapter cannot obtain LIVE authority from a Dhan source at all,
and no application-layer module names the plugin.

`DhanHostConfig.broker_client_id` lets a host built over a custom transport
declare the client identity the adapter binds evidence to; a host built from
credentials derives it from those credentials. When neither is available the
adapter exposes no usable construction path and LIVE composition fails closed
instead of inventing an identity.

`DhanRiskEvidenceSource` is a neutral evidence producer. It is constructed with
the exact account, broker connection, expected `dhanClientId`, transport,
instrument/`DhanInstrumentRef` pairs, and a bounded read timeout. Collection
is profile-first: the authenticated profile must match the expected client id
before funds, positions, or holdings are read. Holdings rows carry no client
id, so their identity is bound by the same authenticated transport rather than
by a row field. Per-row client ids, when present, are corroborating only; a
contradiction rejects the collection.

Funds map to the six financial evidence fields: Dhan's `sodLimit` becomes
cash balance; its `availabelBalance` (vendor spelling) becomes available cash,
margin available, and buying power; `utilizedAmount` becomes margin used; and
`blockedPayoutAmount` becomes blocked cash. If any of the six is missing or
unusable, all six financial observations are dropped instead of exposing a
partial account state. Positions and holdings are both required before
exposure is reported; an unavailable book is never treated as an empty book,
while an absent instrument in an available book is an observed zero. Position
and holding quantity identities, per-row client ids, and canonical instrument
mappings are validated before use.

The Dhan endpoints used here do not provide daily P&L, complete portfolio
equity, a reliable high-water mark, or a mark-to-market portfolio valuation.
Those fields are therefore reported unavailable, never zero. Because the
sanctioned LIVE composition requires daily P&L (and the other mandatory
fields) before it treats evidence as authoritative, this source does not make
the Dhan LIVE path authoritative: public LIVE dispatch stays blocked by
design. Issue #267 remains open.

The positions response also carries `realizedProfit` and `unrealizedProfit`
on individual position rows. QuantX preserves those values in the supplemental
`LiveRiskPositionPnlCollection`, separate from `LiveRiskEvidenceField` and
the `RiskSnapshot`. Each row retains its canonical instrument mapping when
available, signed quantity, optional product/position labels, both broker-
reported P&L amounts, the positions-response observation instant, and explicit
`BROKER_REPORTED` provenance. A missing/non-finite P&L value, unmapped row,
foreign row client id, or unavailable positions book marks the collection
incomplete; rows are not silently dropped to create a complete subset. An
available empty positions response is an empty row collection, not account
P&L of zero.

This supplemental collection is included in the application authority's
per-evaluation integrity seal, but it is not a required risk field, is not
aggregated into account/day P&L, and is never copied into
`RiskSnapshot.daily_pnl`, `equity`, or `high_water_mark`. Its timestamp is
source metadata, not a new daily-P&L accounting basis or a substitute for the
risk authority's mandatory field freshness/completeness checks. Any future
consumer must define its own freshness and accounting semantics before using
these row values in risk decisions. The Dhan LIVE path therefore remains
fail-closed under the existing required fields.

These observations are exercised only through the in-memory transport. No
real broker call, production credential, or LIVE order is part of the
implementation or its tests.

## Market-data composition

```text
MarketDataPort
    ↑
Dhan market-data adapter
    ↑
Dhan transport
```

The Dhan plugin additionally provides a snapshot-only market-data adapter
implementing the canonical `MarketDataPort`: `quote()` and `candles()` are
served from normalized Dhan quote/candle snapshots through the same
transport boundary, using the explicit instrument mappings already present
in the plugin. The application/domain layers remain unaware of the Dhan
SDK: vendor imports stay isolated to `transport.py`, and quote/candle
payloads are normalized to the vendor-neutral `Quote`/`Candle` contracts
before crossing the plugin boundary.

Streaming is explicitly unsupported: `subscribe()`/`unsubscribe()` fail
closed rather than pretending to stream, since Dhan market feed would
require async workers that do not exist in this architecture. Missing
fields stay missing, malformed payloads are rejected, and no market data
is fabricated.

## Order mapping

QuantX order types map as follows:

| QuantX | Dhan |
|---|---|
| MARKET | MARKET |
| LIMIT | LIMIT |
| STOP | STOP_LOSS_MARKET |
| STOP_LIMIT | STOP_LOSS |

Only `DAY` and `IOC` validity are accepted in this adapter. QuantX `GTC`
and `FOK` are rejected before transport submission.

Dhan's current API documentation lists `TRANSIT`, `PENDING`, `PART_TRADED`,
`TRADED`, `REJECTED`, `CANCELLED`, and `EXPIRED` order states. The
adapter maps these to the corresponding QuantX execution and order states;
unknown broker states become `UNKNOWN`.

## Uncertain outcomes

A transport/network exception during submission, cancellation, or
reconciliation produces an `UNKNOWN` execution receipt. The plugin does not
automatically retry order submission.

For a traded order, reconciliation verifies the broker-returned correlation
identity against the deterministic Dhan correlation derived from the request.
It also rejects negative or over-order filled quantities and requires a traded
price before constructing a canonical fill. No price or fill is invented when
the broker does not provide one.

## Operational prerequisite

Dhan's current API documentation states that order placement, modification,
and cancellation require static IP whitelisting. That is an external broker
account/configuration prerequisite, not something the QuantX adapter bypasses.

P1.5 tests use the injected in-memory transport and never require Dhan
credentials or submit real orders.
