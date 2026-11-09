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
  india/               # India-specific rules; implemented venue scope is explicit
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

## Current implementation status — verified on main at `a620b3b13f2cd10c9fee19f61e3afd3121f345ff`

The architecture above describes the intended market-neutral direction. The package names and future-market examples are **target-state**, not a claim that those markets, connectors, currencies or execution modes are implemented.

### Implemented market-module contract

- The canonical India implementation lives under `quantx.markets.india`; `quantx.india` is a deprecated compatibility shim that re-exports the canonical package.
- `MarketModule` is a structural protocol. Its required identity is `region`, `market_contexts`, `market_pack_id` and `rule_version`. `MarketModuleBase` is a convenience implementation, not a subclassing requirement.
- `MarketRegistry` is caller-populated. The current API is `register(module)`, with the region derived from the module; `get(region)` and `get_for_context(context)` provide lookup. Context lookup requires exact membership in the registered module's declared context set. Registration validates the region, non-empty context set, region/context consistency, required metadata and duplicate region.
- The registry does not discover or import market packages automatically. Market selection is explicit composition at the application/research/backtest/paper boundary. A missing registry entry or unsupported context does not silently select another market.
- Trusted market checks are not trusted through pack self-declaration. The core bootstrap pins the exact approved implementation object through its core-owned registrar; identity, region and stage must match the core-owned binding. Do not reintroduce a `ports`-side dynamic import/discovery mechanism as a way to grant trust.
- Reusable session-calendar contracts (`MarketCalendar`, `SessionClassification`, `SessionStatus` and the fixed development calendar) live in `quantx.markets.common.calendar`. `HistoricalCalendar` remains the research-facing protocol in `quantx.research.calendar`, which re-exports the moved market calendar contracts.
- `IndiaMarketModule` currently advertises NSE equity and NSE derivatives contexts. That registry declaration does not imply that every Indian venue, segment or product is implemented through the module.

### Implemented markets and explicit limits

- India is the only implemented market module.
- `quantx.markets.digital_assets` is an unimplemented placeholder: `MARKET_IMPLEMENTED = False`, and its factory returns `None`.
- North America, Europe, UK, Asia-Pacific and other market packages shown in the target structure are not implemented by this migration.
- No cross-currency portfolio accounting, FX conversion, international venue support or additional market connector is delivered by the market-module migration. Cross-market portfolios and currency conversion remain future design topics requiring their own explicit rules and acceptance criteria.
- The migration did not modify `application/live_execution.py` or widen LIVE eligibility. LIVE remains India-only under the existing controls; this document is not authorization to add a LIVE venue or production broker path.

The migration is recorded in [PR #309](https://github.com/jignesh2795/QuantX/pull/309). The earlier PR #295 candidate is stale and remains historical; it was not retargeted or merged. The implementation-specific PR1 plan refines the earlier global plan where the two differed: use structural module registration, explicit context membership and core-owned trusted registration rather than the earlier proposed dynamic `ports` import path. No additional market scaffold or empty capability protocol is required merely to make the architecture diagram look complete.
