# QuantX Crypto Market Extension Plan

**Status:** Planning proposal; not an implementation commitment or release claim.  
**Planning branch:** `docs/crypto-market-extension-plan`  
**Base:** `main` at `a34ec73b3f9457079882ca99b895a8efeae23d73` (2026-10-24)  
**Scope:** Future digital-asset market support while preserving QuantX's universal core and the current Indian-market/execution-safety work.

## 1. Decision

QuantX should retain a first-class architectural path for digital assets. Crypto belongs behind the existing market-context, port, capability and adapter boundaries—not as crypto-specific conditionals spread through the universal order, portfolio, risk or execution core.

This plan does **not** claim that crypto trading is implemented today. The current repository has useful foundations:
- `MarketRegion.GLOBAL` and `MarketFamily.DIGITAL_ASSETS` in `src/quantx/domain/instruments.py`;
- `AssetClass.DIGITAL_ASSET` in `src/quantx/domain/enums.py`;
- a market-neutral instrument and broker/market-data port direction;
- a documented `Digital Assets` market module and Binance venue-adapter example in `docs/architecture/32-global-market-separation.md`.

A digital-asset classification is not, by itself, a complete crypto market module, venue connector, backtest model or permission to submit live orders.

## 1A. Code-backed compatibility findings

**Inspection baseline:** repository main at `a34ec73b3f9457079882ca99b895a8efeae23d73` (2026-10-24). These are source-model observations, not implementation or exchange-integration evidence.

- **Instrument metadata:** the current canonical Instrument has a symbol, AssetClass, MarketContext, one currency, tick size, lot size and multiplier. It has no explicit base-asset, quote-asset, settlement-asset, quantity-step or minimum-notional fields. An adapter/market-pack contract must preserve these venue facts; the project must decide deliberately which belong in shared domain contracts versus market metadata.
- **Derivative maturity:** Contract currently accepts only FUTURE and OPTION, and requires a timezone-aware expiry. A perpetual instrument has no expiry; do not represent one with a fabricated date or infer perpetual support from AssetClass.FUTURE. Derivatives require a separate reviewed contract extension.
- **Multi-asset account state:** AccountFinancialState stores balance, available cash, blocked cash, margin and buying power in one currency. A spot exchange wallet may hold multiple independent assets. Do not collapse raw asset balances into this model or apply implicit conversion; define explicit per-asset balance evidence and valuation/conversion policy where needed.
- **Order semantics:** TimeInForce currently covers DAY, IOC, FOK and GTC. Order product and position-effect fields are generic contracts currently resolved through market-pack policy; India defaults and product semantics must not leak into crypto. Exchange-specific post-only, reduce-only, client-order identity, trigger and quantity semantics need explicit capability/contract treatment before support is declared.
- **LIVE authorization:** build_live_execution intentionally composes the India policy and blocks non-India LIVE execution. Keep that behavior unchanged; crypto LIVE requires a separate sanctioned composition and its own market checks, risk inputs, operator authorization, recovery and reconciliation proof.
- **Implementation reality:** the canonical package map has India and Dhan/reference-broker integrations but no implemented digital-assets market module or exchange connector. A target package path is not evidence of runtime support.

These gaps make the architecture/compatibility audit the first crypto work item. They do not justify a broad universal-domain rewrite or a venue SDK dependency in the core.

## 2. Product boundary and sequencing

**Near-term priority remains current QuantX correctness work.** This plan must not displace execution durability, reconciliation, recovery, LIVE control hardening, or the active Strategy Platform sequence. Crypto implementation should start only when a bounded milestone is selected against the current roadmap and relevant safety prerequisites are met.

Target sequence:

1. **Architecture and compatibility audit.** Verify instrument identity, quantities, currencies, market-data contracts, fees, capability negotiation, persisted identities and execution policy against crypto requirements. Record gaps before implementation.
2. **Crypto spot research/data vertical slice.** Normalize authoritative instrument metadata and historical/live market observations for one selected venue. Preserve provenance, timestamps, exact decimal values, gaps and unavailable evidence. No order submission.
3. **Spot backtest fidelity.** Add crypto-aware rules and explicit assumptions for fees, spread/slippage, quantity precision, minimum quantity/notional, and 24/7 timestamps. A strategy must not pass by relying on fabricated liquidity or inferred fills.
4. **Spot paper execution.** Run the canonical order lifecycle using the existing safety path and simulated fills. Exercise partial fills, rejections, timeouts, unknown submission outcomes, reconciliation and restart/recovery. No real order submission.
5. **Venue test-environment integration and independent gate.** If the selected venue exposes a suitable official test environment, validate its adapter there without treating that as production certification. Record venue capability evidence and operational limitations.
6. **Live spot only after an explicit approval gate.** Add market-specific live composition, risk policy, account/connection identity, permission checks, recovery, reconciliation, kill-switch and operational evidence as a separately reviewed slice. The current India-only LIVE region policy must not be bypassed or weakened to enable crypto.
7. **Derivatives as a separate later expansion.** Perpetual swaps and exchange-traded crypto futures need explicit contracts for funding, leverage, margin, liquidation, position mode, reduce-only semantics and exchange-specific close behavior. Do not infer support from spot compatibility.
8. **Additional venues and cross-market portfolios.** Add only after the first vertical slice proves the adapter and capability contracts. Keep INR/USDT/USD (and other quote currencies), valuation, conversion provenance, and aggregate risk explicit.

Each phase should have a small, reviewable acceptance matrix and an exact candidate-SHA validation report. Stop and document a blocker instead of broadening scope to get a green result.

## 3. Architectural shape

Keep the dependencies pointing inward:

```text
Strategy / Research
        |
TradeIntent -> policy + risk -> canonical order lifecycle
        |                         |
Universal QuantX domain       execution ports / receipts
        |                         |
Market-context rules          venue adapter (outside core)
        |
Digital-assets market module
```

Responsibilities should remain separated:

- **Universal core:** canonical instrument/order/fill/position/portfolio semantics, event time, risk interfaces, idempotency, receipts, recovery and reconciliation contracts.
- **Digital-assets market rules:** symbol and instrument normalization, base/quote currencies, tick/step size, minimum quantity/notional, trading availability, fee schedules, and supported product-specific constraints.
- **Venue adapter/plugin:** credentials, network transport, exchange payload mapping, venue error normalization, native identifiers, API-specific behavior and authoritative account/order observations.
- **Research/backtest layer:** dataset identity/provenance, timestamp and gap treatment, execution assumptions, fee/funding model identity and fidelity reporting.
- **Market capability descriptor:** explicit product types, order types, market-data modes, cancellation/replacement behavior, precision constraints, account and position features. Unsupported capabilities must be rejected before dispatch.
- **Application / LIVE composition:** explicit market policy and permissions. A plugin must not gain live authority merely by registering or advertising a capability.

The target module path in architecture record 32 is `src/quantx/markets/digital_assets/`, with venue adapters under the plugin boundary (for example, a future Binance plugin). Before creating packages, reconcile this target with the current canonical package map and module-boundary rules rather than forcing a large directory refactor.

## 4. First venue and product scope

Select **one venue and spot product** for the first vertical slice after checking its current API, terms, supported test environment, rate limits and data rights. Binance is a documented candidate, not a pre-approved dependency or a claim of current compatibility.

Initial scope should be narrow:
- spot instruments and normalized market data;
- one explicitly selected quote-currency set;
- market and limit order semantics only where the venue's capabilities and lifecycle can be represented faithfully;
- authoritative balances, orders, fills and positions where the selected adapter can supply them;
- local research, deterministic backtesting and paper trading;
- capability and contract tests that run without real credentials.

Explicitly out of the first slice: live orders, leverage, perpetuals, funding, liquidation handling, cross-exchange arbitrage, portfolio transfers, custody, DeFi/on-chain activity, automated deposits/withdrawals, and AI agents with privileged execution access.

## 5. Crypto-specific correctness requirements

- **24/7 calendar:** Do not reuse Indian exchange sessions or assume a daily close. Represent UTC instants consistently and handle venue timestamps and missing intervals explicitly.
- **Exact values and constraints:** Use decimal-safe price/quantity/money values. Preserve tick size, step size, minimum quantity/notional, contract multiplier, base asset, quote asset and settlement asset where applicable. Reject nonconforming values at a defined boundary; never round silently in the core.
- **Order lifecycle:** Normalize venue responses into canonical receipts and lifecycle states. A timeout or ambiguous response is an unknown outcome—not evidence of rejection and not permission to resubmit.
- **Recovery and reconciliation:** Bind submissions to durable idempotency/order identity, account and connection. Resolve uncertain outcomes using authoritative venue evidence; otherwise remain blocked/pending and surface the uncertainty.
- **Fees and execution realism:** Identify which fees are observed versus modeled. Include spread, slippage, partial fills and rejected orders only to the degree supported by explicit evidence/model assumptions. Do not present OHLC bars as proof of executable liquidity.
- **Risk:** Distinguish spot holdings from liabilities and derivative exposure. Apply explicit per-order, instrument, account and daily-loss limits. Any risk aggregation across quote currencies requires explicit, provenance-bearing conversion rates.
- **Credentials and permissions:** Keep keys outside source control and domain objects; separate read-only data credentials from trade-capable credentials where the venue supports it; never enable withdrawals for the trading adapter. Redact secrets and sensitive payloads from diagnostics.
- **Capability truth:** Do not declare an order type, product, stream, margin feature or test environment supported until it has contract tests and documented venue evidence.
- **India/global separation:** Global digital assets and Indian-market products may share core contracts but must not share assumed regulations, sessions, settlement, taxes, margin rules or LIVE eligibility. Regulatory/account constraints require their own reviewed policy and are not inferred by this architecture plan.

## 6. Release gates for the first crypto spot slice

A candidate is not ready to advance unless its report demonstrates all applicable items:

1. Domain/architecture boundary tests pass; no venue SDK types or network code leak into universal domain/application contracts.
2. Instrument metadata and candle/trade data are normalized from explicit source evidence; timestamps, decimal values, missing data and provenance survive persistence/readback without fabrication.
3. Capability negotiation rejects unsupported combinations before any dispatch.
4. Backtest results identify the dataset, strategy/run configuration, fee/fill model and limitations; reproducible tests verify deterministic behavior.
5. Paper lifecycle tests cover success, partial fill, rejection, cancellation, timeout/UNKNOWN, reconciliation and restart/recovery.
6. No paper/replay/backtest path can accidentally dispatch live orders; no live path is introduced by the initial research/data slice.
7. Exact-SHA focused and full local test results, lint, format, strict typing (where configured), migration checks and diff checks are recorded. Do not claim GitHub CI ran unless an actual workflow run is observed.
8. Documentation distinguishes implemented behavior, tested integration behavior, simulated assumptions and future capability.

Live trading requires a separate, explicit readiness review and must not be implied by a passing paper or exchange-test-environment run.

## 7. Deliverables before implementation

The first implementation proposal should contain:
- a current-code compatibility/gap audit against the canonical package map and execution boundaries;
- a venue/product comparison with dated sources and a justified first choice;
- a small capability matrix covering data, order types, precision, account state, reconciliation and test support;
- an ADR only if a universal contract or the current India-only LIVE policy must change;
- a phased acceptance matrix with explicit non-goals and test evidence.

Do not add a new broker SDK dependency, alter order semantics, change the market-context schema, expand LIVE region eligibility, or change the main roadmap simply to make this proposal executable. Each such change must be independently justified and reviewed.

## 8. Repository references

- `docs/architecture/32-global-market-separation.md` — global market and digital-assets separation.
- `docs/architecture/06-indian-market-domain.md` — Indian-first domain and extension rule.
- `docs/architecture/adr/ADR-005-indian-market-domain-first.md` — Indian-market-first decision with a venue-neutral core.
- `docs/architecture/adr/ADR-006-broker-adapters-and-capabilities.md` — adapter/capability boundary.
- `docs/architecture/13-plugin-contract.md` — intended plugin contract (working draft).
- `docs/architecture/28-v0.1-acceptance-criteria.md` — v0.1 scope does not certify production LIVE broker execution.
- `docs/roadmap/README.md` and `docs/STATUS.md` — current sequencing and implementation evidence.

## Decision summary

Keep crypto in the target architecture, implement it incrementally as a market module plus venue plugin, begin with research/data and spot paper trading, and require a separate safety review before live trading. This planning document adds no crypto trading capability and makes no live-readiness claim.
