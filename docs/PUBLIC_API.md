# QuantX public Python API

## Purpose

`quantx.api` is the deliberately small import boundary for application authors.
It re-exports canonical domain objects; it does not introduce wrapper classes or
a second implementation of any contract.

Use the names in `quantx.api.__all__` for new application code. Internal
package paths remain useful to QuantX maintainers, but they are not the
compatibility boundary for downstream consumers.

## Current public surface

The exact exported-name snapshot is:

```python
from quantx.api import (
    AssetClass,
    Contract,
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
    Money,
    OptionType,
)
```

The corresponding `quantx.api.__api_stability__` metadata classifies each
export. The module's snapshot test keeps the documented list and runtime
`__all__` aligned.

### Stability tiers

| Tier | Meaning | Current membership |
|---|---|---|
| Stable | Compatibility is part of the supported public contract and breaking changes follow the stable deprecation policy. | None. |
| Provisional | Intended for downstream use, but names or semantics may change before 1.0. | Every name in `quantx.api.__all__`. |
| Internal | Any import not listed in `quantx.api.__all__`, including implementation modules, application services, execution internals, adapters and plugins. | All other QuantX imports. |

QuantX is currently `0.1.0.dev0`. No export is labelled stable at this
pre-1.0 stage. The market taxonomy values describe classifications; they do
not assert that every region, family, venue or asset class is implemented.
India remains the only fully implemented market, and the digital-assets
module remains a placeholder.

## Compatibility and deprecation policy

### Before 1.0

- The public API is provisional. A pre-1.0 release may contain incompatible
  changes to provisional names or behavior.
- An intentional incompatible change to `quantx.api` should be recorded in
  the changelog with a concise migration note.
- Where feasible, a deprecated provisional name should emit
  `DeprecationWarning` and its removal target should be documented. There is
  no fixed pre-1.0 deprecation window.
- Security, data-integrity or correctness fixes may require an earlier
  incompatible correction; such changes should still be described in the
  release notes where disclosure is safe.

### Stable API policy

No stable imports are promised today. Before any name is promoted to stable,
its semantics, supported inputs, failure behavior and compatibility tests
must be explicitly reviewed and documented. Once a stable API is declared,
removal or incompatible change requires a documented deprecation period and
migration path; the period must be stated when the stable guarantee is
introduced rather than assumed retroactively.

### Internal imports

Imports outside `quantx.api.__all__` are internal, even when a package
`__init__.py` happens to re-export them. Internal names may be moved,
renamed or removed without a public deprecation window. Downstream code
should not infer public status from current importability.

## Design constraints

- The facade points directly to canonical domain classes. It does not copy,
  subclass or wrap them.
- Imports are limited to domain leaf modules. Importing `quantx.api` must not
  load the application composition root, the Dhan plugin/SDK, or perform
  network I/O.
- The public module does not expose application composition, production/LIVE
  builders, broker adapters, risk services, or execution lifecycle internals.
  Those APIs have separate safety and compatibility concerns.
- `Quantity` is not exported in this first snapshot. Its current runtime
  constructor does not enforce the finite-`Decimal` contract expected of a
  general public quantity type; it should be reviewed independently before
  being promoted.
- `MarketContext`, `MarketRegion`, `MarketFamily` and `AssetClass` are
  classification contracts, not a registry of supported venues or a claim
  that all represented markets are operational.

## Example

```python
from decimal import Decimal

from quantx.api import Money

notional = Money(Decimal("1250.00"), "INR")
```

Money values require finite `Decimal` amounts. Arithmetic between different
currencies fails rather than performing an implicit conversion. This does
not provide FX conversion or multi-currency portfolio support.

## Change control

The exact `__all__` list is locked by
`tests/unit/test_api.py::test_public_api_exports_match_documented_snapshot`.
Changing that list requires updating this document and reviewing the
compatibility implications in the same change. The public-API import test
also runs in a fresh interpreter with network socket entry points blocked
and asserts that neither the optional Dhan SDK/plugin nor the application
composition package is imported.
