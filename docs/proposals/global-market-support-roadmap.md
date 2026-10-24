# Global Market Support — Staged Roadmap Proposal

**Status:** PROPOSAL ONLY — not approved, not merged  
**Branch:** `docs/global-architecture-proposal-2026-10`  
**Baseline:** `a34ec73b3f9457079882ca99b895a8efeae23d73`  
**Purpose:** Define gates for moving from a market-neutral architecture toward additional validated market implementations.

## 1. Governing rule

A market is not supported merely because its region or asset class can be represented by the domain model. Support requires an implementation, authoritative rules and data, adapter behavior, conformance tests, documented limitations, and a clear execution-eligibility decision.

The existing India-only LIVE composition is a safety boundary. This proposal does not authorize removing or bypassing it.

## 2. Stages

### Stage 0 — Baseline and architecture evidence

- Freeze the audited source revision for comparison.
- Complete the comparative architecture audit.
- Build an import/dependency map for `domain`, `application`, `execution`, `india`, `plugins`, `research`, and `integrations`.
- Inventory all India-specific types and assumptions, including currency, product type, order validity, session rules, derivative contracts, charges, and margin.
- Label every capability as implemented, tested, supported, or deferred.

**Exit gate:** No high-priority architectural recommendation rests solely on documentation or assumptions.

### Stage 1 — Universal contracts and market-pack contract

- Define the minimum market-pack interface and lifecycle.
- Define required instrument, rule-version, provenance, capability, and policy evidence.
- Make unsupported or missing market requirements fail closed.
- Establish reusable contract and negative-path tests.
- Verify the universal core has no dependency on concrete market packs.

**Exit gate:** A synthetic non-India pack can be validated in tests without granting production LIVE eligibility.

### Stage 2 — Select one additional market

Select the first additional market only after comparing developer demand, data availability, API accessibility, legal/regulatory constraints, integration effort, and the amount of new domain behavior required.

Candidate examples for evaluation, not commitments:
- Digital assets through one exchange.
- US equities through one brokerage.
- Another international market with an accessible, well-documented adapter.

Do not implement all regions at once.

**Exit gate:** A written decision selects one market, one integration, its initial instrument scope, and its explicit non-goals.

### Stage 3 — Data and research vertical

- Implement instrument discovery and metadata validation.
- Implement historical and live data normalization as required.
- Define timestamp, missing-data, precision, provenance, and quality behavior.
- Add market-specific calendar and rule data.
- Prove deterministic replay and backtest behavior with fixtures.
- Model costs and market-specific trading constraints.

**Exit gate:** Repeatable tests prove data identity, rule versioning, and deterministic research for the declared scope.

### Stage 4 — Paper/sandbox execution vertical

- Implement one concrete broker or venue plugin.
- Add adapter conformance tests for capabilities and unsupported operations.
- Test order submission, partial fills, cancellations, rejection, timeout, unknown outcome, reconciliation, and restart recovery as applicable.
- Verify account and market context isolation.
- Verify no vendor SDK types leak into universal contracts.
- Test risk and policy checks with both allowed and rejected requests.

**Exit gate:** The full supported workflow is demonstrated in paper or sandbox mode without real capital or production order submission.

### Stage 5 — LIVE eligibility review

This stage is separate from market integration.

Before any new market becomes LIVE-eligible, require:
- Explicit market-specific production policy and trusted rule provenance.
- Validated account, instrument, and market context.
- Market-specific risk, capital, session, and order constraints.
- Durable fail-closed gate behavior and startup recovery.
- Idempotency and uncertain-submission evidence.
- Reconciliation and operator-resolution workflows.
- Secret handling, logging, and operational runbooks.
- Fault-injection and negative-path tests.
- A reviewable release artifact with known limitations.

**Exit gate:** An explicit, reviewed decision changes LIVE eligibility for that market. Until then, the existing India-only restriction remains.

### Stage 6 — Expand incrementally

Only after one additional market has passed its declared gates should QuantX generalize further. Use evidence from the first implementation to improve the contracts before adding more integrations.

## 3. Market support matrix — current audit baseline

This matrix records findings from the read-only audit and must be updated with new evidence.

| Area | Current evidence | Proposed next step |
|---|---|---|
| Universal domain | Market region/family/context and common instrument models exist | Audit assumptions and invariants |
| India market rules | Dedicated `src/quantx/india/` implementation exists | Preserve; use as first market-pack reference |
| Dhan broker | Concrete plugin exists | Preserve adapter isolation and expand conformance evidence where needed |
| Reference broker | Test-oriented adapter exists | Reuse for generic lifecycle tests, not as proof of a real-market integration |
| Crypto exchange | No Binance plugin found in the audited source layout | Evaluate as one candidate, not an assumed commitment |
| US brokerage | No Alpaca plugin found in the audited source layout | Evaluate only after comparative audit |
| Other regions | Region enums and target documentation exist | Do not equate representation with support |
| LIVE outside India | Current composition deliberately blocks non-India requests | Retain until a market passes Stage 5 |

## 4. Architectural constraints

- No repository split as part of this roadmap.
- No mass refactor of execution/recovery modules.
- No changes to existing India execution behavior without targeted evidence and tests.
- No market-specific rules in universal `domain/` modules.
- No broker-name conditionals replacing capability contracts.
- No silent defaults for missing instrument or market evidence.
- No claims of production support based solely on unit tests or an instantiated adapter.
- No AI/ML expansion until core market/data/execution contracts and the initial vertical are coherent.

## 5. Change-control protocol

Each stage should have a short implementation plan that identifies:
- Exact baseline SHA and allowed files.
- Contract changes and consumers.
- Compatibility constraints.
- Positive and negative tests.
- Validation commands and results.
- Explicit non-claims.
- A separate review decision before merging.

This roadmap itself is planning-only. It changes no release scope, code behavior, or LIVE authorization.

## 6. Decisions still open

1. What market and asset class should be the first non-India vertical?
2. Which exact capabilities belong in the universal market-pack contract versus optional capabilities?
3. What evidence qualifies a market as supported versus LIVE-eligible?
4. Which reference-project patterns are worth adopting after the comparative audit?
5. Which current documentation should eventually be updated on `main`, and in what order?


## 7. Initial venue priorities and sequencing clarification

The first delivery is aimed at Indian traders, but the target architecture is global. Evaluate Delta Exchange India and Binance as initial candidate venue priorities alongside the Indian-market broker/API ecosystem. Do not treat either venue as implemented, validated, or supported until the audit confirms it from source and tests. For Binance, record product scope separately (for example spot versus derivatives); for Delta Exchange India, record exact products, account mode, sandbox/test environment, and jurisdiction-specific constraints.

Implementation order is evidence-led: complete the baseline/reference audit; confirm universal contracts and a synthetic non-India pack; select one vertical based on user value, API/data access, cost, and safety; complete data/research and paper/sandbox execution with failure-path evidence; then conduct a separate LIVE eligibility review. Do not change the current India-only LIVE policy in the meantime.

## 8. Indian broker/API research gate

Before selecting or expanding Indian broker coverage, compare official API documentation and relevant open-source projects for Zerodha Kite Connect, Upstox, Dhan HQ, Angel One SmartAPI, Fyers, Shoonya, OpenAlgo, and other actively maintained candidates found. Record authentication/session behavior, order/product semantics, rate limits, streaming and historical data, instrument-master quality, sandbox availability, reconciliation support, API terms, and current access restrictions. These are evaluation candidates only; no integration is promised by this list.

Distinguish a broker gateway/control plane from a trading engine. Learn from broker-normalization and onboarding patterns without moving strategy semantics, risk controls, or execution integrity into an untrusted external gateway.

## 9. Market acceptance evidence

A vertical is not complete until its acceptance package contains: exact baseline SHA and supported venue/product scope; official rule/API sources and review date; instrument and market-rule fixtures with provenance/versioning; data-quality and deterministic replay/backtest evidence; adapter contract tests including negative/unsupported-capability cases; paper/sandbox lifecycle tests for partial fills, rejects, cancellation, timeout/unknown outcome, reconciliation, and restart recovery where applicable; security, rate-limit, logging, operator runbook, and known-limitations notes; and explicit implemented, validated, supported, and LIVE-eligible decisions.
