# Digital-Assets Market Expansion

**Status:** Proposed future roadmap; not active implementation, not a release claim.
**Baseline reviewed:** main at a34ec73b3f9457079882ca99b895a8efeae23d73.
**Scope:** establish a safe path from QuantX's universal trading contracts to crypto spot first, with derivatives and cross-venue portfolio support separately gated.

## Objective and guardrails

QuantX should support digital assets as an additional market family without becoming crypto-specific at its core. Reuse the canonical strategy, risk, order lifecycle, execution receipts, persistence, recovery, reconciliation, research provenance and paper/backtest semantics wherever their contracts fit. Put venue protocol, symbol mapping, exchange rule data and market-specific behavior behind existing ports and plugin boundaries.

This is a roadmap entry, not a commitment to start immediately. Execution correctness, recovery, LIVE control hardening and the active Strategy Platform sequence retain priority. Crypto work starts only when a bounded milestone is explicitly selected against the current status and its safety prerequisites.

Non-negotiable guardrails:

- Do not change or weaken the current India-only sanctioned LIVE composition to enable crypto.
- No real broker/exchange orders in development or validation.
- No venue SDK or credentials in universal domain/application/execution code.
- No silently inferred currency, precision, fee, market-hours, margin, fill or capability evidence.
- UNKNOWN submission outcomes remain unresolved until authoritative reconciliation; they are never treated as rejection or safe-to-resubmit.
- A plugin manifest or capability claim is not LIVE authorization.

## Current compatibility findings

The current code has useful extension primitives: digital-asset classification, global/digital-assets market context, market-neutral instrument/order/position contracts, market-data and broker ports, explicit capability sets, and durable execution/recovery boundaries.

It is not yet crypto-ready:

| Contract area | Current gap | Required disposition before support |
|---|---|---|
| Instrument identity | Canonical Instrument has one currency field and lacks explicit base, quote and settlement asset identities, quantity step and minimum notional. | Define authoritative venue metadata and decide which portable facts belong in shared contracts versus the digital-assets market pack. |
| Multi-asset account state | AccountFinancialState represents financial measures in a single currency. | Preserve raw per-asset balances; define valuation currency and provenance-bearing conversion rules rather than silently aggregating unlike assets. |
| Derivative contract | Contract currently requires an expiry and only supports FUTURE/OPTION. | Spot first. Design and review expiry-less perpetual semantics before any perpetual/futures product is claimed. |
| Order policy | Time-in-force and product/position-effect contracts do not automatically cover every exchange-specific flag. | Capability-gate post-only, reduce-only, trigger, client identity, quantity denomination and other unsupported semantics. Never silently drop a requested behavior. |
| Market policy | The sanctioned LIVE composition enforces India-only policy. | Keep it unchanged; create a separate crypto LIVE composition only after its own safety review. |
| Venue integration | No digital-assets market package or crypto exchange connector is currently implemented. | Select one venue/product through dated evidence and contract tests; do not infer support from target architecture. |

These findings are based on source inspection, not successful exchange calls or live trading evidence. See [the detailed Crypto Market Extension Plan](../planning/crypto-market-extension-plan.md).

## Target architecture

- **Universal core:** canonical orders, fills, positions, portfolio accounting, event time, risk interfaces, receipts, idempotency, reconciliation and recovery.
- **Digital-assets market rules:** instrument normalization, base/quote/settlement identities, price tick and quantity step, minimum quantity/notional, supported order rules, fees, venue status and product constraints.
- **Venue adapter/plugin:** authentication, transport, rate limiting, symbol translation, native order identifiers, response/error normalization, streaming/reconnect, balances, open orders, fills and authoritative reconciliation evidence.
- **Research layer:** dataset identity, source/timestamp provenance, gaps, exact decimal values, fee/slippage assumptions, and execution-fidelity limitations.
- **LIVE composition:** explicit risk limits, trusted clock, market-pack verification, disarmed durable gate, credential permissions, idempotency, quarantine evidence, recovery and reconciliation. A venue adapter cannot self-authorize.

The target package layout must be reconciled with the current package map before implementation. Do not create a parallel architecture or do a broad directory migration merely to match a suggested future path.

## Phased sequence

### DAX-0 — Contract and compatibility audit

**Purpose:** turn the gaps above into a bounded, testable design before selecting a library or venue.

Deliverables:
- Compare a dated set of candidate venues and their spot APIs, data rights, rate limits, terms, account semantics and official test facilities.
- Define instrument identity and the authoritative source/version of tick size, quantity step, minimum notional, base/quote assets and trading status.
- Define per-asset account evidence and explicit valuation/conversion policy.
- Map existing order, receipt, idempotency, UNKNOWN, cancellation and reconciliation contracts to venue lifecycle behavior.
- Record which capabilities can be expressed faithfully and which must be rejected.
- Identify schema/versioning and backward-compatibility impacts before proposing shared-contract changes.

Exit gate: a reviewed gap matrix, selected first venue/product with dated sources, no unresolved claim that the existing contracts already cover a missing semantic, and an acceptance matrix for DAX-1. No exchange SDK or LIVE change is required in this phase.

### DAX-1 — One-venue spot data vertical

Normalize instrument metadata and market observations for one selected venue. Preserve source identity, event/observation timestamps, Decimal values, gaps, stale/missing evidence and dataset version through storage and readback. The first slice performs no order submission.

Exit gate: provider contract tests, deterministic normalization tests, data provenance and gap tests, and no fabricated candles, prices, liquidity or balances.

### DAX-2 — Spot research and backtest fidelity

Connect the data vertical to the canonical research pipeline. Version fee schedules and execution assumptions; model spread, slippage, precision, minimum quantity/notional and partial fills only to the degree explicitly supported. Historical OHLC bars alone are not proof of executable liquidity.

Exit gate: reproducible runs bind dataset, strategy/configuration, cost/fill model and limitations; deterministic tests cover gaps, timestamps, fee application and invalid precision. No LIVE path.

### DAX-3 — Spot paper execution

Use the canonical order lifecycle and paper executor with a crypto-specific versioned rule/cost profile. Do not make an independent execution engine. Cover accepted, rejected, partially filled, cancelled, timed-out, UNKNOWN, reconcile and restart/recovery outcomes.

Exit gate: PAPER cannot dispatch to a live adapter; unresolved submissions stay pending and block unsafe retries; restart/recovery cannot submit orders; balances and fees reconcile to explicitly simulated evidence.

### DAX-4 — Venue test-environment contract tests

Use an official venue sandbox/testnet only if it exists and supports the required product and endpoints at the time of implementation. Record the tested endpoints, limitations and timestamped evidence. A testnet pass is not production certification.

Exit gate: documented capabilities and negative-path test results, sanitized diagnostics, credential/permission isolation, and no claim of production LIVE readiness.

### DAX-5 — Restricted LIVE spot, separately gated

Add a distinct digital-assets LIVE composition rather than expanding the India composition. Require independently reviewed market checks, explicit risk limits, trusted freshness time, durable disarmed gate, exact account/connection identity, least-privilege credentials, authoritative order/balance evidence, reconciliation, quarantine, recovery and operational disable procedures.

Exit gate: a separate exact-SHA readiness review covers all LIVE safety boundaries and proves unsupported products/flags, missing evidence, malformed responses, clock failures, gate failures and UNKNOWN outcomes block safely. No live orders are part of implementation validation.

### DAX-6 — Derivatives

Perpetual swaps and expiry-dated crypto futures are separate products. Before either is enabled, define their contract identity, settlement/collateral, margin, leverage, funding, liquidation, position mode, reduce-only and close semantics, valuation and risk exposure. Perpetual instruments must not receive invented expiry dates.

Exit gate: reviewed domain contracts, independent accounting/risk tests, venue capability tests and paper/recovery evidence for each supported product type.

### DAX-7 — Additional venues and cross-market portfolios

Add more venues only after the first spot vertical demonstrates stable adapter contracts. Cross-market portfolios require explicit asset conversion, source and timestamp provenance, conversion staleness limits and risk aggregation; never combine INR, USD, USDT or other balances as if they were interchangeable.

Exit gate: adapter conformance, explicit multi-currency valuation policy and portfolio-risk tests that reject missing or stale conversion evidence.

## Cross-phase acceptance gates

Every implementation phase must provide an exact-candidate-SHA report and the applicable evidence below:

1. Boundary tests prove vendor SDKs and transport concerns do not leak into universal domain/application contracts.
2. Capability negotiation rejects unsupported product/order combinations before dispatch.
3. Prices, quantities and money use Decimal-safe representations; invalid precision or missing rule evidence is rejected rather than silently rounded or guessed.
4. Dataset, instrument metadata, fees, fills, funding (when applicable) and valuation evidence have explicit source/version/time identity.
5. Paper/replay/backtest cannot reach a live exchange submit path.
6. UNKNOWN, timeout, persistence failure and restart/recovery cases preserve unresolved evidence and block unsafe resubmission.
7. Credentials are not committed, diagnostics are redacted, and trading keys do not receive withdrawal permission.
8. Focused and full local tests, Ruff, formatting, strict typing where configured, migration checks and diff checks are reported exactly. Do not imply GitHub Actions ran without an observed workflow.
9. Documentation distinguishes implemented code, contract-tested adapter behavior, venue-test-environment behavior, simulated assumptions and unimplemented targets.

## Explicit non-goals for the first spot vertical

No leverage, perpetuals, expiry-dated derivatives, liquidation, cross-exchange arbitrage, deposits/withdrawals, custody, DeFi/on-chain activity, broad multi-venue support, distributed services or AI agents with privileged execution. Each requires its own scope and acceptance gate.

## References

- [Global Market Separation](../architecture/32-global-market-separation.md)
- [Broker Adapters and Capabilities ADR](../architecture/adr/ADR-006-broker-adapters-and-capabilities.md)
- [Plugin Contract](../architecture/13-plugin-contract.md)
- [Current Package Map](../architecture/41-current-package-map.md)
- [Execution Safety Audit](../architecture/56-live-execution-safety-audit-and-priority.md)
- [QuantX Status](../STATUS.md)
- [Crypto Market Extension Plan](../planning/crypto-market-extension-plan.md)

**Status statement:** This roadmap defines intended sequencing and acceptance criteria only. It adds no crypto implementation, does not select an exchange for production, and does not authorize crypto LIVE orders.
