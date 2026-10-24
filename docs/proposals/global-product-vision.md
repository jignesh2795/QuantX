# QuantX Global Product Vision — Proposal

**Status:** PROPOSAL ONLY — not approved, not merged  
**Branch:** `docs/global-architecture-proposal-2026-10`  
**Baseline:** `a34ec73b3f9457079882ca99b895a8efeae23d73`  
**Purpose:** Align the long-term product identity with a global, multi-market open-source trading engine without expanding current LIVE execution permissions.

## 1. Proposed product statement

QuantX is an open-source, modular, event-driven algorithmic trading engine and infrastructure platform designed to support multiple asset classes, markets, and broker or venue integrations through explicit, testable contracts.

The universal core owns market-independent trading semantics. Market packs own jurisdiction-, venue-, and asset-class-specific rules. Broker and data-provider plugins implement external-system integration contracts.

India is the initial implementation focus, not the permanent boundary of the product.

## 2. Product scope versus current support

These concepts must not be conflated:

- **Vision:** markets and workloads the architecture intends to accommodate.
- **Implemented:** code exists in the repository.
- **Validated:** relevant behavior is covered by repeatable tests and evidence.
- **Supported:** documented compatibility, integration tests, operational requirements, and maintenance commitments exist.
- **LIVE-eligible:** a market has separately satisfied the required production safety gates.

A market's presence in `MarketRegion` or `MarketFamily` does not establish implementation, support, or LIVE eligibility.

## 3. Architecture principles to preserve

1. Market-neutral domain contracts for orders, fills, positions, portfolio accounting, events, execution lifecycle, and risk interfaces.
2. Explicit market context carried with instruments, accounts, connections, and requests where required.
3. Market-specific rules and instrument metadata behind market-pack boundaries.
4. Broker authentication, payload mapping, transport, reconciliation, and vendor SDKs inside concrete plugins.
5. Capability-based compatibility checks instead of scattered vendor-name conditionals.
6. Consistent semantics across backtest, replay, paper, and live environments, with environment-specific evidence and controls.
7. Fail-closed behavior when authoritative market, account, instrument, or risk evidence is missing.
8. Modular monolith and local-first operation until evidence justifies a more complex deployment.
9. No global LIVE enablement without a separate safety review and explicit market eligibility.

## 4. Proposed logical architecture

```text
Applications / API / CLI / notebooks / optional AI agents
                         |
                Application services
                         |
       Universal domain + execution contracts
                         |
          Market-pack and provider interfaces
               /          |           \
            India      Global       Digital assets
               \          |           /
                 Broker / data plugins
                         |
              Persistence and runtime
```

This is a target-level conceptual view, not a claim that all packages or integrations currently exist.

## 5. Market-pack responsibilities

A market pack should define or supply explicit, versioned contracts for:

- Market context and supported instrument families.
- Instrument and derivative-contract metadata requirements.
- Session calendars, trading permissions, holidays, and time zones.
- Tick size, lot size, quantity precision, price bands, and order constraints.
- Supported order types, time-in-force, product semantics, and position effects.
- Fees, transaction costs, settlement, corporate actions, funding, and margin where applicable.
- Pre-trade checks and trusted rule provenance.
- Required market-data capabilities and data-quality constraints.
- Tests proving both allowed and rejected cases.

A broker plugin remains separate: a broker is not the definition of the market.

## 6. Explicit non-goals for this proposal

- No immediate repo split.
- No mass package migration.
- No deletion or weakening of the current India-only LIVE restriction.
- No claim that Binance, Alpaca, Interactive Brokers, or any other unimplemented provider is supported.
- No changes to code, runtime behavior, credentials, broker configuration, CI, or release status.
- No PR or merge implied by creating this proposal branch.

## 7. Acceptance criteria for a future approved change

Before this proposal is adopted, reviewers should confirm:

- README, VISION, and architecture overview use consistent product positioning.
- Existing v0.1 scope and release claims remain accurate.
- The current implementation map is distinguished from target architecture.
- Market support is described with explicit implementation and validation evidence.
- The India-only LIVE behavior is documented as a current safety constraint.
- No proposed wording implies unsupported global LIVE execution.

## 8. Decision requested from maintainers

Review this proposal alongside the comparative audit and market-support roadmap. Accept, amend, or reject it explicitly before any changes are transferred to `main`.


## 9. Initial delivery scope — clarification

The product is globally architected, while the first delivery is deliberately narrower. The initial user focus is traders in India, with initial venue priorities to be evaluated around Indian-market access and crypto access through Delta Exchange India and Binance. This is product intent, not evidence that either integration is implemented or supported.

For every venue, maintain separate labels for targeted, implemented, validated, supported, and LIVE-eligible. A venue is not implemented because it appears in a roadmap; it is not supported until compatibility, limitations, tests, and maintenance expectations are documented. Do not describe QuantX as globally LIVE-capable merely because its core is market-neutral. India remains the only LIVE-eligible jurisdiction until a separately reviewed decision changes that policy. Crypto support must be assessed by venue and product type, such as spot versus derivatives.
