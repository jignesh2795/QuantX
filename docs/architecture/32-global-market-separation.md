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

## Digital-assets extension boundary (target; not implemented)

The universal domain already classifies digital assets and market contexts, but classification is not a supported crypto trading product. The first bounded implementation should target spot trading and explicit market-data provenance; exchange-specific behavior belongs in a digital-assets market module and venue adapter, not in India rules or universal execution conditionals.

The current model has specific compatibility gaps that must be resolved or explicitly bounded before claiming broad crypto compatibility: the canonical instrument has one currency field rather than explicit base, quote and settlement asset identities; account financial state is single-currency rather than a multi-asset wallet ledger; and the derivative contract model requires expiry, so it cannot faithfully represent an expiry-less perpetual contract. These are design gates, not reasons to weaken the existing contracts with fabricated values.

The sanctioned LIVE composition is currently India-only. Crypto must receive a distinct, explicitly composed and independently reviewed LIVE path; the India policy must not be bypassed, widened or silently replaced. Registration of a venue plugin or advertisement of a capability is not authorization to trade.

The target implementation sequence and acceptance gates are maintained in [Digital-Assets Market Expansion](../roadmap/digital-assets-market-expansion.md), with a code-backed planning proposal in [Crypto Market Extension Plan](../planning/crypto-market-extension-plan.md). Both documents describe future work, not current support.
