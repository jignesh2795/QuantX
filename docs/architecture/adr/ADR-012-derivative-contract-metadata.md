# ADR-012: Canonical Derivative Contract Metadata and Resolution

**Status:** Accepted (2026-10-16)

**Issue:** [#194 — QX-05 preserve derivative contract metadata](https://github.com/jignesh2795/QuantX/issues/194)

**Decision scope:** Domain and resolution contract only. This ADR does not claim derivative catalog/resolution changes are implemented.

## Context

The current `quantx.domain.instruments.Contract` stores an `Instrument` plus optional `underlying`, `expiry`, `strike`, and free-string `option_type`. Its validator checks a supplied strike is positive and a supplied option type spells CALL or PUT case-insensitively, but it does not require the complete metadata for derivative asset classes, validate an expiry timestamp, or store a canonicalized option type. The current test `test_contract_accepts_call_option_metadata` proves that `"call"` remains stored as lowercase `"call"`.

The current point-in-time `VersionedInstrumentRule` / `PointInTimeInstrumentRegistry` returns effective-dated tradability, tick size, lot size, multiplier, currency, and rule version. That rule contract does not carry underlying, expiry, strike, or option type. The broker plugin's `DhanInstrumentRef` is a vendor mapping, not canonical derivative contract metadata. Strategy/order construction and risk inputs also currently operate from `InstrumentId`/\`Instrument\` without a canonical, versioned contract resolution being bound through the approved request.

The architecture must preserve stable instrument identity while making derivative metadata explicit, point-in-time resolvable, and lossless from source catalog through risk and execution evidence. Parsing symbols or using today's metadata as a historical fallback is not acceptable.

## Decision

**Keep tradable instrument identity and derivative contract metadata as separate but explicitly linked domain concepts. Resolve them through one explicit, versioned result that carries both the canonical instrument and the applicable contract metadata.**

The canonical resolution result contains:
- the canonical `Instrument` and stable `InstrumentId`;
- optional canonical derivative `Contract` metadata keyed by that `InstrumentId`;
- the uniquely selected point-in-time instrument rule and contract metadata version(s);
- source/provenance and effective-time identity sufficient to bind the resolution to research, risk and execution.

The `Contract` metadata record refers to its instrument by stable `InstrumentId`; it does not contain a second independent `Instrument` copy. `Instrument` remains the owner of tradable symbol/market/currency/tick/lot/multiplier facts. `Contract` owns derivative underlying, expiry, strike and option type. Do not duplicate those derivative fields onto `Instrument`.

## Required contract

### 1. Canonical derivative fields

- Introduce one domain-owned `OptionType` vocabulary (CALL and PUT) and use that type in canonical contract metadata. Raw vendor strings are normalized and validated at the adapter/source boundary; they do not circulate as free strings in core domain objects.
- `InstrumentId` remains the stable identity. Contract metadata is linked to the instrument rather than inferred from the human-readable symbol.
- A listed option contract requires a canonical underlying `InstrumentId`, a valid expiry instant, a positive strike, and an `OptionType`. Missing fields fail construction/catalog registration closed.
- A future contract requires a canonical underlying `InstrumentId` and a valid expiry instant; strike and option type are not applicable and must be absent. The applicable market pack may add stricter family-specific requirements but may not weaken these universal completeness rules for the corresponding asset class.
- Non-derivative instruments have no derivative contract record unless a separately documented market-specific contract type requires one. Do not synthesize empty derivative metadata to make a resolution appear complete.
- Preserve the current timezone-aware `datetime` expiry concept unless a separately reviewed API migration establishes another canonical form. Expiry must be timezone-aware, and source adapters must convert exchange-local expiry dates/instants using explicit market/session rules. Do not silently attach a timezone to a naive timestamp or infer an expiry instant from the symbol.

### 2. Canonical ownership and compatibility

- Keep the `Instrument` and contract metadata responsibilities separate. Do not duplicate underlying/expiry/strike/option type across `Instrument`, `Contract`, broker references and historical rules.
- The canonical contract type references `InstrumentId` rather than embedding a second `Instrument` object. A resolution object returns the one canonical `Instrument` together with the optional `Contract` record and rule/provenance metadata.
- Where the public or internal API changes the current `Contract(instrument=...)` construction, make the change explicit and update all consumers/tests in one compatibility-audited migration. Any temporary adapter must convert to the canonical representation at the boundary; it must not permit contradictory instrument copies or competing `OptionType` definitions.
- Keep vendor-specific security IDs and symbols in adapter reference types. They can map to the stable QuantX `InstrumentId`, but they are not the canonical contract catalog and cannot substitute for its metadata.
- A missing or malformed derivative contract is not repaired by guessing the underlying, strike, expiry, option type, lot size, or multiplier from a symbol string or another instrument.

### 3. Effective-dated resolution

- Contract metadata has explicit source identity/version and effective-time semantics. Corrected or changed source records must be represented as versioned evidence rather than overwriting the historical meaning of an instrument silently.
- Keep instrument trading-rule versioning (tick, lot, multiplier, currency, tradability) separate from derivative contract metadata versioning. The resolution API composes the two at an explicit timestamp; it must not overload the existing `VersionedInstrumentRule` with a second lifecycle.
- The point-in-time resolver returns exactly one valid instrument rule and, for derivatives, exactly one applicable contract record. Missing or overlapping/conflicting candidates fail closed.
- The historical resolution must preserve the selected metadata version and its provenance. It may not fall back to current catalog metadata when a historical record is absent.
- Contract validity/expiry and point-in-time tradability remain distinct. Having a contract record does not imply the contract was tradable at the requested time; existing market-session and instrument-tradability checks still apply.

### 4. Strategy, risk, execution and serialization path

- Trace the complete resolved contract context from the source catalog through instrument resolution, strategy intent/order preparation, risk evaluation, approved request, adapter mapping and persisted/replayable evidence.
- Strategy-facing and execution-facing APIs continue to identify the instrument with `InstrumentId`; wherever a consumer needs derivative specifics, it must receive the explicit resolved contract context instead of parsing the symbol or doing an unversioned lookup.
- Before risk approval, the request must bind the exact resolved contract identity/version and the relevant instrument-rule version. Risk/charges/margin evaluation for derivatives must consume that resolved context.
- The approved execution request or its immutable persisted evidence must retain a stable reference/fingerprint of the selected contract metadata, so restart, receipt audit and replay do not silently bind the same instrument to a different current contract record.
- Extend the existing canonical request fingerprint to include the selected contract metadata identity/version whenever it changes execution semantics. Do not add a second fingerprint or contract identity in the broker adapter.
- The Dhan adapter uses its explicit canonical `InstrumentId` mapping to choose the wire security. Contract metadata comes from the canonical resolver. The adapter must not parse expiry/strike/option type from a trading symbol to fill gaps.

## Acceptance tests

The implementation must prove, at the exact reviewed SHA:

1. Underlying, expiry, strike and option type round-trip losslessly from the registered contract source through canonical resolution and approved request/replay evidence.
2. Option records missing underlying, expiry, strike or option type fail construction/registration; invalid/non-positive strike, naive expiry, and invalid option type also fail closed.
3. Futures require underlying and expiry and reject option-only strike/option-type fields; non-derivative instruments are not forced to carry derivative metadata.
4. One canonical `OptionType` type is used in the domain and consumers; vendor string spellings are converted only at explicit source/adapter boundaries.
5. Resolution returns the canonical `Instrument` and applicable `Contract` metadata without duplicating or contradicting the instrument identity.
6. Point-in-time resolution selects one historical contract/rule version, rejects overlapping or missing metadata, and never falls back to today's contract details.
7. The selected contract/rule identity is preserved through risk evaluation, approved execution request, fingerprinting, serialization/recovery and deterministic replay.
8. No expiry/strike/underlying/option type/lot-size/multiplier is inferred from symbol strings or unrelated current metadata.
9. Existing `InstrumentId` identity, effective-dated rule intervals, market-session policy, receipt/request identity, broker lifecycle, and no-LIVE safety boundaries remain unchanged.

## Alternatives considered

### Put derivative fields on Instrument — rejected

It conflates a tradable venue instrument with contract-specific facts, duplicates ownership and creates ambiguity when the same market-neutral instrument model is reused across venues or contract versions. It also cannot clearly represent instrument-rule history separately from contract metadata history.

### Keep Contract optional/incomplete and normalize at use sites — rejected

Consumers would continue to receive incomplete records and independently interpret free strings or missing fields. That can diverge between research, risk, order preparation and adapters and allows a malformed derivative contract to appear valid.

### Infer contract details from symbols/vendor references — rejected

Symbol conventions change and are not the canonical domain contract. Vendor mappings are adapter details and may omit fields. Inference can silently bind the wrong strike or expiry and contaminate historical research/replay with current metadata.

## Consequences and implementation gates

This contract adds an explicit resolution seam but preserves instrument identity and the existing point-in-time trading-rule model. The first implementation must inventory every constructor, registry/catalog, strategy/order path, risk/charges consumer, Dhan mapping and serializer before moving fields. Keep QX-04's product/position-effect contract separate: product is order semantics, while underlying/expiry/strike/option type are derivative contract metadata. Both are needed before QX-07 moves shared contracts between packages.

This ADR settles the design for QX-05 (#194). **It does not close issue #194 or claim the catalog, resolution API, OptionType, risk binding, or serialization changes have shipped.**
