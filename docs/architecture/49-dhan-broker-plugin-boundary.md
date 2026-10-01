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

The adapter currently advertises only the capabilities implemented by the
existing QuantX `BrokerPort` contract:

- order submission
- order cancellation

Positions, balances, replacement, and other Dhan functionality remain
outside the first adapter slice until QuantX exposes normalized contracts
for them.

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
