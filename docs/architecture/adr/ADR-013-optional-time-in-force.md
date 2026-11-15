# ADR-013: Optional Time-in-Force in Canonical Orders

**Status:** Accepted (2026-11-15)

## Context

The canonical `Order` and `TradeIntent` contracts previously required a
`TimeInForce` value and defaulted it to `DAY`. That preserves existing
India order construction but cannot represent a market order whose venue
semantics have no time-in-force field. Encoding `GTC` as a substitute for
absence is semantically incorrect, and adding a synthetic `NOT_APPLICABLE`
member to the universal enum would confuse an absent request property with an
actual time-in-force policy.

Order-type/time-in-force applicability is market-pack semantics. It must not
be imposed as one universal order-type matrix because markets and adapters
have distinct capabilities.

## Decision

The canonical field type is `TimeInForce | None` on both `TradeIntent`
and `Order`.

1. **Backward-compatible default:** both fields retain `TimeInForce.DAY` as
   their constructor default. Existing callers that omit the field retain
   their established behavior.
2. **Explicit absence:** callers may pass `None` when no time-in-force value
   applies. `None` is not IOC, FOK, GTC, or an implied venue default.
3. **Market-specific policy:** market packs validate exact order-type/TIF
   pairs. The initial Digital Assets spot fixture supports `MARKET + None`
   and `LIMIT + GTC`; it does not treat the independently supported type
   and TIF sets as a cross-product.
4. **Adapter safety:** an adapter or execution model that has not defined
   semantics for an absent TIF must reject it before transport or execution.
   This change does not make Dhan or the existing paper executor accept
   `None`; both continue to require their explicit supported values.
5. **Identity:** the canonical request fingerprint includes `null` when TIF
   is absent. Existing non-null fingerprints retain the same TIF string and
   legacy DAY requests therefore keep their previous fingerprint payload.
6. **Projection:** `build_order_from_intent` carries the optional value
   unchanged. No strategy, risk, accounting, or execution component may
   silently convert absence to a venue-specific value.

## Compatibility and persistence

The default remains DAY, so callers relying on omitted TIF do not change.
New callers must pass `None` explicitly to represent absence. Dhan mapping
and the existing generic paper executor reject `None` locally rather than
translating it.

The idempotency store persists execution receipts and a separate, versioned
`PendingExecutionContext` request projection sufficient for recovery. The
projection serializes the relevant order fields as JSON rather than storing
a raw `Order` or `TradeIntent` object. Its existing `time_in_force` field now
writes JSON `null` for absence and restores that value as `None`; the legacy
`DAY` value remains the string `"DAY"`. The canonical request fingerprint
also includes `null`, distinct from the previous DAY string. The existing
pending-context JSON version already supports this value, so no context or
receipt schema-version migration is required.

## Consequences

- Existing India DAY/IOC behavior remains governed by the India pack and
  adapter contracts.
- Markets can express an absent TIF without adding vendor semantics to the
  core enum.
- Unsupported execution paths fail closed until they define explicit
  no-TIF behavior.
- Every market pack must publish a pair-specific capability matrix and test
  both supported and unsupported combinations.
