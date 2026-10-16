# ADR-011: Order Product and Position Effect Are Request Semantics

**Status:** Accepted (2026-10-16)

**Issue:** [#193 — QX-04 product and position effect](https://github.com/jignesh2795/QuantX/issues/193)

**Decision scope:** Canonical contract and migration requirements only. This ADR does not claim the fields or market-pack resolution are implemented.

## Context

The current `TradeIntent` and `Order` carry instrument, side, quantity, order type, prices, time-in-force and execution context, but no explicit order product or position effect. `request_fingerprint()` hashes those existing order semantics. The Dhan adapter's `DhanInstrumentRef` currently includes `product_type`, and `build_order_request()` copies that mapping-level value onto every order for the mapped instrument. Thus product choice is currently bound to instrument mapping rather than being an explicit, fingerprinted request choice.

That is not sufficient for a market-neutral contract: one instrument can legitimately be traded under different products, and product selection may change margin, charges, eligibility, and order handling. Position effect is likewise an instruction about the intended exposure change, not a property of the instrument. A broker may not expose a literal open/close wire field, but the platform still needs to validate and retain the requested semantics.

## Decision

**Order product and position effect are per-order request semantics. Product definitions and their defaults are owned by the applicable market pack; broker adapters only translate the already-resolved approved request. Neither value is part of immutable instrument identity.**

Keep the universal core free of broker-specific product enums such as Dhan wire values. Use a validated opaque product identifier (for example, a `ProductCode` value object) that is interpreted under an explicit market-pack/product-rule version. Use one canonical `PositionEffect` vocabulary for the broadly applicable semantic choices `OPEN`, `CLOSE`, and `AUTO`, while allowing the field to be absent only where the selected product/market pack says it is not applicable or has a documented compatibility default.

## Required contract

### 1. Request flow and ownership

- Carry product selection and requested position effect from `TradeIntent` through `Order` construction, risk/policy evaluation and `ApprovedExecutionRequest`. Do not leave either value as adapter-only configuration.
- The resolved approved request must identify the effective product and applicable market-pack/product-rule version. It must also retain the requested position effect and, when `AUTO` is resolved, the effective position effect used for approval.
- Product definitions, support by asset/segment, defaults and mappings from neutral product identity to broker wire values belong in market-pack/adapter contracts. A universal core enum containing the product vocabularies of individual brokers is rejected.
- Product/position-effect validation must happen before authoritative reservation completion or broker submission. An unsupported combination is rejected before transport side effects.
- Preserve each selected value in the durable order/request representation and relevant receipt/request evidence. Serialization or recovery must not reconstruct product/effect from the instrument symbol or a current mutable mapping.

### 2. Product selection and defaults

- A product is an explicit request attribute, validated against the applicable market pack, instrument/asset class, venue/segment, order side and effective rule set.
- A product code has meaning only within its applicable market-pack context. The same code string in two contexts is not assumed to mean the same economic behavior.
- Omitted product selection is not a universal default. A market pack may define a documented, versioned compatibility default for a specific supported context. Resolution must bind the selected product and rule version before final risk approval and execution.
- If no unique supported product/default can be resolved, fail closed. Do not pick the first product, infer a product from a symbol, or treat adapter capability as proof that the product is supported.
- During Dhan migration, the current product choice embedded in `DhanInstrumentRef.product_type` must be moved into an explicit market-pack default/selection configuration. It must not remain the per-order source of truth. The Dhan wire product type is derived from the approved order product; the adapter rejects any product it cannot map or support.
- Keep legacy callers compatible only through an explicit, tested compatibility default that preserves existing intended behavior for the applicable context. Do not introduce a silent global default.

### 3. Position effect semantics

- `OPEN` expresses that the order is intended to open or increase exposure under the selected product and market rules; ordinary side, shorting/borrow, margin and risk constraints still apply.
- `CLOSE` expresses that the order must reduce an existing eligible position. It must not cross through zero into a new/reverse position. A requested close larger than the authoritative closable position is rejected or explicitly split only by a separately specified policy; this ADR does not authorize an automatic split.
- `AUTO` asks the applicable market pack to resolve open/close treatment against authoritative position evidence and its own rules. `AUTO` is not a fallback for missing or stale position data. If current position evidence is unavailable, stale, conflicting or incomplete, a market pack that requires that evidence must fail closed.
- An absent effect is distinct from `AUTO`. It means the caller did not specify a position effect; only an explicitly documented product/market default or a declared not-applicable rule may resolve it.
- The market pack determines whether these semantics are meaningful for a given product/asset class and whether they have broker-wire representation. If the broker has no open/close field, the adapter does not fabricate one; the requested/effective effect remains enforced and recorded by the platform policy/risk path.
- The resolved effect and the position-evidence cut used for `AUTO` must be fixed before the final authorization/reservation. It may not be recomputed later during adapter submission against different position state.

### 4. Fingerprints and identity

The canonical execution request fingerprint must include all execution-relevant selected/resolved semantics, including:

- resolved product code;
- requested position effect and the resolved effective effect when applicable;
- market-pack/product-rule identity and version (or an equally stable, canonical rule identity);
- the existing instrument, side, quantity, order type, prices, time-in-force, account/portfolio/deployment, market and required capabilities.

The client-order identity and timestamps may remain excluded as today, but differing product/effect choices must not collide to the same fingerprint. An attempt to reuse an existing client order ID for a different product or effective position effect must be rejected by the existing idempotency boundary rather than treated as the same request.

Do not duplicate request fingerprinting in a market pack or broker adapter. Update the existing canonical fingerprint path and retain its exact deterministic Decimal/serialization conventions.

### 5. Dhan adapter boundary

- `DhanInstrumentRef` remains the identity/venue mapping (for example, Dhan security ID, exchange segment and trading symbol); its `product_type` must stop acting as the per-order selected product.
- `DhanOrderRequest.product_type` is populated by mapping the approved product selection using the supported Dhan product vocabulary. Different supported order products for the same canonical `InstrumentId` must produce different corresponding wire values and request fingerprints.
- The adapter rejects a request product absent from its verified mapping for that instrument/segment. It does not silently fall back to the instrument reference's old `product_type` after the migration.
- Broker-specific wire representation remains isolated to `quantx.plugins.dhan`; no Dhan names are added to universal domain enums.

## Acceptance tests

The implementation must establish all of the following at the exact reviewed SHA:

1. The same instrument and otherwise identical order economics can select two supported products, generating different canonical fingerprints and the expected distinct Dhan wire product values.
2. Product selection is preserved from `TradeIntent` through `Order`, approved request, serialization/recovery and adapter mapping.
3. Unsupported product/market/asset-class combinations and invalid product defaults are rejected before broker submission or reservation completion.
4. Explicit `OPEN`, `CLOSE`, `AUTO`, and absent/not-applicable effect cases follow the market-pack contract; `CLOSE` cannot reverse a position through zero.
5. `AUTO` with unavailable/incomplete/stale required position evidence fails closed, and resolved effect is bound to the same evidence cut used for approval.
6. Different effective position effects or rule versions produce different fingerprints wherever they alter execution semantics; same ID plus mismatched fingerprint remains blocked by the existing idempotency gate.
7. Legacy callers without explicit fields behave only through a documented, context-specific compatibility default, with regression fixtures proving that behavior.
8. Existing replay timestamps, receipt validation, risk/policy order, durable PENDING/UNKNOWN semantics and Dhan timeout/no-auto-retry behavior remain unchanged.

## Alternatives considered

### Product remains inside instrument mapping — rejected

One instrument may be eligible for multiple product choices. A mapping-level product prevents the request from expressing that choice and causes economically different requests to share the same instrument-side configuration.

### One universal enum of broker product strings — rejected

The vocabulary and semantics differ by market pack and adapter. A single enum populated with vendor codes would leak adapter concepts into the neutral core and would not define support, defaults or effective-dated rules.

### Infer position effect from side or the current net position alone — rejected

BUY/SELL does not uniquely mean OPEN/CLOSE, and net position alone does not establish eligibility under product/venue rules. AUTO requires explicit, authoritative evidence and deterministic resolution before approval. Missing evidence is not a default.

## Consequences and implementation gates

The core order semantics become explicit and fingerprinted while market packs retain ownership of applicability/defaults and adapters retain only wire translation. This adds a required resolution point before final risk approval; that point must use a coherent market/position evidence cut and preserve the existing reserve-before-submit and fail-closed guarantees.

Implementation must audit all `TradeIntent` construction, `Order` builders, risk inputs, approval/recovery serialization, request fingerprinting, Dhan reference/configuration construction, and Dhan order mapping together. The product/effect migration must not be implemented only in the happy-path submit adapter, and no public field should be added without tracing persistence and recovery compatibility.

This ADR settles the contract design for QX-04 (#193). **It does not close issue #193 or claim the request fields, product resolver, fingerprint changes, or adapter migration have shipped.** QX-05 (#194) remains the separate gate for canonical derivative contract metadata.
