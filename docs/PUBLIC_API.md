# QuantX public Python API

## Supported import boundary

`quantx.api` is the curated public Python import surface. Consumers should
import public contracts from this module rather than depending on internal
package paths:

```python
from quantx.api import (
    Candle,
    InstrumentId,
    MarketContext,
    MarketDataPort,
    MarketFamily,
    MarketRegion,
    Money,
    Quote,
    TradeIntent,
)
```

The exact export list is `quantx.api.__all__`. A snapshot test locks this list.
The package root, `quantx`, continues to expose only `__version__`; importing
the public API is explicit and does not eagerly import application services,
broker plugins, the optional Dhan SDK, or perform network access.

The surface is deliberately curated rather than a convenience re-export of
every domain class. It contains market-neutral identity, instrument and market
context values; order-intent vocabulary; deterministic time abstractions;
market-data observations and ports; and the validated Money value object.
It does not publish application composition or broker submission authority.
`FixedClock` remains internal because it is a test helper.
`ExecutionMode.LIVE` describes a requested execution context; it does not
grant permission, establish account authority, or establish broker readiness.

## Stability tiers

| Tier | Meaning | Current status |
|---|---|---|
| Stable | Explicitly designated for compatibility guarantees under the stable release policy. | No symbols are designated stable yet. |
| Provisional | Intentionally public, but subject to compatibility changes while QuantX is pre-1.0. | Every name in `quantx.api.__all__`. |
| Internal | Implementation detail with no public compatibility promise. | Every symbol not listed in `quantx.api.__all__`, including direct submodule imports. |

A symbol does not become stable merely because it is exported, documented, or
used by an in-repository plugin. Stable designation requires an explicit
release decision and documentation update. Runtime metadata in
`quantx.api.__api_stability__` classifies every exported name as
`provisional`; the mapping is immutable and must match `__all__`.

## Pre-1.0 compatibility policy

The package currently declares version `0.1.0.dev0` and Python
`>=3.12,<3.13`. Until a 1.0 release:

- All `quantx.api` exports are provisional.
- A breaking change to a provisional symbol may occur in a later 0.y release;
  pre-1.0 releases do not promise the compatibility guarantees of SemVer 1.0.
- When practical, a removal or rename will first be documented as deprecated
  and called out in release notes or migration notes. This is a best-effort
  policy, not a guarantee that every pre-1.0 breaking change has a full
  deprecation cycle.
- Correctness, data-integrity and security fixes may require immediate
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

## Current provisional surface

The exact names are maintained in `quantx.api.__all__` and grouped here by
responsibility:

- **Identity and market context:** `AccountId`, `BrokerConnectionId`,
  `InstrumentId`, `PortfolioId`, `ProductCode`,
  `StrategyDeploymentId`, `AssetClass`, `Contract`, `Instrument`,
  `MarketContext`, `MarketFamily`, `MarketRegion`, and `OptionType`.
- **Money:** `Money`, whose constructor requires a finite `Decimal` amount
  and whose addition/subtraction requires matching currencies. It does not
  provide currency conversion or imply multi-currency portfolio support.
- **Order intent and execution context:** `ExecutionContext`,
  `ExecutionMode`, `OrderSide`, `OrderType`, `PositionEffect`,
  `TimeInForce`, and `TradeIntent`.
- **Market data:** `Candle`, `Quote`, `MarketDataPort`, and
  `MarketDataStore`.
- **Time:** `Clock`, `SimulatedClock`, and `SystemClock`.

The context and asset taxonomy is broader than implemented market support.
India remains the only fully implemented market; digital assets is a
placeholder. An enum value or caller-provided `MarketContext` is not evidence
that a venue, instrument family, data source or execution path is supported.

For deterministic replay or repeated strategy evaluation, callers should
supply an explicit deterministic `TradeIntent.intent_id`; its default UUID
factory is not a replay-stability guarantee.

## Deliberate exclusions

The public API does not currently export:

- `Quantity`: its current runtime constructor does not enforce the finite
  `Decimal` and exact numeric-type contract expected of a general public
  quantity value. Review and strengthen that value object separately before
  exposing it.
- Strategy authoring/runtime symbols whose public semantics have not yet been
  explicitly designated.
- Risk-evidence authority, LIVE execution composition, broker submission
  ports, execution receipts, persistence implementations, or vendor SDK
  types. In particular, this API does not imply that LIVE trading is
  supported or ready; issue #267 remains open and public LIVE dispatch remains
  fail-closed.
- Market-specific implementation modules. Market rules remain behind the
  market-module boundary and are not promoted into the universal core API.

These exclusions prevent an early public import surface from becoming a
blanket promise about unfinished semantics or internal implementation
details.

## Compatibility and validation

Public imports are required to work without optional Dhan dependencies and
without network access. The API module imports only domain contracts and the
vendor-neutral market-data ports; it does not import application composition,
integrations or broker plugins. Static import-boundary assertions and an
isolated fresh-process smoke test lock that requirement.

The export snapshot and import-boundary tests live in
`tests/unit/test_api.py`. The tests also check canonical object identity,
immutable stability metadata and the Money invariants. This policy describes
the current source contract; it does not claim a published package release or
a 1.0 stability guarantee.
