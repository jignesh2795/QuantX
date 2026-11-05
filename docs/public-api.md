# QuantX Public Python API

## Supported import boundary

quantx.api is the curated public Python import surface. Consumers should
import public contracts from this module rather than depending on internal
package paths:

    from quantx.api import (
        Candle,
        InstrumentId,
        MarketContext,
        MarketDataPort,
        MarketFamily,
        MarketRegion,
        Quote,
        TradeIntent,
    )

The exact export list is quantx.api.__all__. A snapshot test locks this list.
The package root, quantx, continues to expose only __version__; importing
the public API is explicit and does not eagerly import application services,
broker plugins, the optional Dhan SDK, or perform network access.

The current surface is intentionally focused on market-neutral domain values,
order intent and time contracts, and market-data interfaces. It does not
publish application composition or broker submission authority.

## Stability tiers

| Tier | Meaning | Current status |
|---|---|---|
| Stable | Explicitly designated for compatibility guarantees under the stable release policy. | No symbols are designated stable yet. |
| Provisional | Intentionally public, but subject to compatibility changes while QuantX is pre-1.0. | Every name in quantx.api.__all__. |
| Internal | Implementation detail with no public compatibility promise. | Every symbol not listed in quantx.api.__all__, including direct submodule imports. |

A symbol does not become stable merely because it is exported, documented, or
used by an in-repository plugin. Stable designation requires an explicit
release decision and documentation update.

## Pre-1.0 compatibility policy

The package currently declares version 0.1.0.dev0 and Python >=3.12,<3.13.
Until a 1.0 release:

- All quantx.api exports are provisional.
- A breaking change to a provisional symbol may occur in a later 0.y release;
  pre-1.0 releases do not promise the compatibility guarantees of SemVer 1.0.
- When practical, a removal or rename will first be documented as deprecated
  and called out in release notes or migration notes. This is a best-effort
  policy, not a guarantee that every pre-1.0 breaking change has a full
  deprecation cycle.
- Correctness, data-integrity, and security fixes may require immediate
  incompatible corrections. Such changes should be explained in the relevant
  release notes.
- The exact public export snapshot and import-boundary tests must be updated
  deliberately when the public surface changes.

For a future 1.x stable designation, stable symbols will be kept backward
compatible within the major version. A stable symbol should be deprecated in
a minor release, documented with a replacement where available, and retained
through at least the next minor release before removal in a major release.
Security or data-integrity fixes may require an exception, with the reason
documented.

## Current surface

The provisional exports are grouped by responsibility:

- **Identity and market context:** AccountId, BrokerConnectionId,
  InstrumentId, PortfolioId, ProductCode, StrategyDeploymentId, AssetClass,
  Contract, Instrument, MarketContext, MarketFamily, MarketRegion, and
  OptionType.
- **Order intent and execution context:** ExecutionContext, ExecutionMode,
  OrderSide, OrderType, PositionEffect, TimeInForce, and TradeIntent.
- **Market data:** Candle, Quote, MarketDataPort, and MarketDataStore.
- **Time:** Clock, FixedClock, SimulatedClock, and SystemClock.

## Deliberate exclusions

The public API does not currently export:

- Money; its value invariants and currency-safe arithmetic remain tracked
  separately in issue #201.
- Strategy authoring/runtime symbols whose public semantics have not yet been
  explicitly designated.
- Risk-evidence authority, LIVE execution composition, broker submission
  ports, execution receipts, persistence implementations, or vendor SDK
  types. In particular, this API does not imply that LIVE trading is
  supported or ready; issue #267 remains open and public LIVE dispatch remains
  fail-closed.
- Market-specific implementation modules. Market rules remain behind the
  market-module boundary and are not promoted into the universal core API.

These exclusions are intentional. They prevent an early public import surface
from becoming a blanket promise about unfinished semantics or internal
implementation details.

## Compatibility and validation

Public imports are required to work without optional Dhan dependencies and
without network access. The API module imports only domain contracts and
market-data ports; it does not import application composition or broker
plugins.

The export snapshot and isolated import smoke test live in
tests/unit/test_public_api.py. This policy describes the current source
contract; it does not claim a published package release or a 1.0 stability
guarantee.
