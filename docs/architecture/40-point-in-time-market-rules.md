# Point-in-Time Market and Instrument Rules

Historical research must never apply today's instrument metadata to a historical timestamp without evidence that the metadata was valid then.

## Rule selection

```text
Historical timestamp T
        ↓
PointInTimeInstrumentRegistry
        ↓
Exactly one effective rule
        ↓
tradability + tick + lot + multiplier + currency + rule version
```

Each rule has an explicit `effective_from`, optional `effective_to`, and `rule_version`. Overlapping intervals for the same instrument are rejected.

## Missing metadata

If no unique rule exists for an instrument at timestamp `T`, resolution fails. The system must not infer lot size, multiplier, currency, listing state, expiry, or tick size from current metadata or from a different contract.

## Tradability

Instrument state is explicit:

- `TRADABLE`
- `NOT_LISTED`
- `EXPIRED`
- `SUSPENDED`
- `UNKNOWN`

A `TRADABLE` market session does not imply that every instrument was tradable. Research must evaluate both market session state and point-in-time instrument state.

## Market-specific implementation

The core only defines the versioned contract. India/global market plugins provide actual historical instrument masters, contract changes, expiries, lot-size revisions, tick-size revisions, trading suspensions, and listing intervals.

This keeps India-specific and global rules separate while allowing the research engine to consume the same point-in-time interface.
