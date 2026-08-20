# State Ownership, Reconciliation, and Recovery

## Purpose

Define authoritative state, reconciliation, restart, reconnect, and recovery behavior before live trading is implemented.

## State ownership

| State | Primary source of truth | Secondary/derived state |
|---|---|---|
| Market data | Data adapter/event stream | Cached/latest quote |
| Orders | QuantX order ledger + broker reconciliation | UI projections |
| Fills | Execution/fill ledger, reconciled with broker | Position/portfolio projections |
| Positions | QuantX position ledger, reconciled with broker | Strategy/UI projections |
| Holdings | Broker account source where applicable | Portfolio projection |
| Funds/margin | Broker account source | Cached risk state |
| Portfolio | QuantX portfolio engine | Analytics/UI |
| Risk state | QuantX risk engine | Monitoring/UI |
| Strategy state | Strategy runtime | Registry/UI |
| Audit history | Immutable event/audit store | Search/index projections |

## Reconciliation rules

1. Broker account state is authoritative for broker-owned facts such as actual orders, fills, holdings, funds, and margin.
2. QuantX is authoritative for its internal intent, risk decisions, strategy state, and local projections.
3. Reconciliation must never silently overwrite discrepancies.
4. Every discrepancy produces an auditable reconciliation event.
5. Live trading must enter a safe state when reconciliation cannot establish a trustworthy state.

## Recovery sequence

```text
Process start
  -> load durable state
  -> connect adapters
  -> authenticate
  -> fetch broker orders/fills/positions/funds
  -> reconcile
  -> rebuild projections
  -> validate risk state
  -> mark runtime READY
  -> resume strategy execution
```

No live strategy may resume before reconciliation completes successfully.

## Failure modes

QuantX must account for:

- process crash
- broker timeout
- broker disconnect
- WebSocket disconnect
- missed events
- duplicate events
- out-of-order events
- partial fills
- stale market data
- corrupted local state
- broker/API degradation

## Idempotency

Live commands should use stable request and idempotency identifiers. QuantX targets at-least-once transport with idempotent command handling and reconciliation; it does not assume arbitrary brokers provide exactly-once semantics.

## Restart modes

- **Cold start:** complete state load and full broker reconciliation.
- **Warm restart:** restore durable state followed by reconciliation before resuming.
- **Safe restart:** restore state but remain non-trading until explicit recovery criteria are met.

## Safety invariant

A restart, reconnect, or reconciliation failure must fail closed: it may stop new trading, but must never silently create new live exposure.