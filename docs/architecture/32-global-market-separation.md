# Global Market Separation

## Decision

QuantX separates markets explicitly from the beginning. The universal core remains market-neutral, while market-specific rules, calendars, instruments, fees, margin, sessions, symbols, settlement, and broker behavior live behind market-specific modules/plugins.

## Principle

Do not build India-specific behavior into the universal order, position, portfolio, or execution primitives merely because India is the first target market.

Instead:

```text
Universal Core
    |
    +-- Market Context
           |
           +-- India
           +-- North America
           +-- Europe
           +-- UK
           +-- Asia Pacific
           +-- Global / Cross-market
           +-- Digital Assets
           +-- future markets
```

An instrument carries a `MarketContext` identifying its region, market family, venue, and optional country code. Market rules are selected from that context.

## Suggested structure

```text
src/quantx/domain/
  instruments.py       # universal identity + MarketContext

src/quantx/markets/
  common/              # cross-market reusable policies
  india/               # NSE/BSE/MCX/NFO/BFO and Indian rules
  north_america/       # future US/Canada modules
  europe/              # future EU modules
  uk/                  # future UK modules
  asia_pacific/        # future APAC modules
  digital_assets/      # crypto-specific market behavior
```

These market packages should be capability modules, not dependencies of the universal kernel.

## Separation boundaries

### Universal core owns

- order lifecycle
- fills
- positions
- portfolio accounting
- risk interfaces
- execution interfaces
- clock/events
- money/quantity primitives
- instrument identity
- plugin contracts

### Market modules own

- trading sessions and calendars
- symbol/instrument master normalization
- contract specifications
- lot and tick rules
- expiry conventions
- settlement rules
- price bands and market-specific constraints
- market-specific fee/charge schedules
- margin models where applicable
- corporate-action rules
- market-data normalization details
- regulatory configuration specific to that market

### Broker adapters own

- authentication
- broker API semantics
- broker order capabilities
- broker-specific symbol mappings
- broker-specific execution and reconciliation behavior

## Market context versus broker

A market and a broker are deliberately separate concepts.

Example:

```text
Market = INDIA / DERIVATIVES / NSE
Broker = Dhan
```

or:

```text
Market = GLOBAL / DIGITAL_ASSETS / BINANCE
Broker/Venue Adapter = Binance
```

The broker adapter must not become the definition of the market.

## Cross-market portfolios

The portfolio layer may eventually contain positions across multiple markets, but each position retains its market context. Currency conversion, valuation and risk aggregation are explicit policies rather than implicit assumptions.

## v0.1

India is the first complete market module. Other market packages may initially contain only interfaces, capability metadata, or placeholders until implemented. This keeps global separation in the architecture without forcing premature multi-market implementation.