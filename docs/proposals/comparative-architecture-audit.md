# QuantX Comparative Architecture Audit Plan

**Status:** PLANNING DOCUMENT — proposed, not approved or merged  
**Branch:** `docs/global-architecture-proposal-2026-10`  
**Baseline:** `a34ec73b3f9457079882ca99b895a8efeae23d73`  
**Purpose:** Compare QuantX's actual implementation with mature open-source trading projects before deciding which architecture changes are justified.

## 1. Audit rule

Compare implemented code and test evidence, not only README claims or architecture diagrams. A design described in a reference project is not automatically suitable for QuantX; record the problem it solves, the trade-offs, and the evidence for adopting it.

This document defines a research method and preliminary hypotheses. It is not a completed source-by-source comparison of all listed projects.

## 2. Reference projects

### LEAN — QuantConnect

Official repository: https://github.com/QuantConnect/Lean

Investigate:
- Algorithm/runtime boundaries and brokerage interfaces.
- Security, symbol, market-hours, exchange, and data normalization models.
- Brokerage-specific behavior versus common order semantics.
- Backtest/live consistency and fee, fill, and slippage models.
- Extension points and the practical cost of supporting many asset classes.

Question for QuantX: which domain concepts should be universal contracts, and which belong to market, data, or brokerage implementations?

### NautilusTrader

Official repository: https://github.com/nautechsystems/nautilus_trader

Investigate:
- Event-driven architecture and canonical order/execution events.
- Instrument identity and venue-specific instrument metadata.
- Adapter/data-client/execution-client boundaries.
- Deterministic simulation and live execution semantics.
- Performance-oriented components versus developer-facing interfaces.

Question for QuantX: are our lifecycle, event, instrument, and adapter contracts sufficiently explicit and coherent?

### Hummingbot

Official repository: https://github.com/hummingbot/hummingbot

Investigate:
- Exchange connectors and connector capability differences.
- Strategy/controller/executor separation.
- Exchange-specific symbol, order, and account behavior.
- Configuration, paper trading, and connector testing.

Question for QuantX: what connector contracts and conformance tests are needed for digital-asset venues without leaking exchange behavior into the core?

### OpenAlgo

Official repository: https://github.com/marketcalls/openalgo

Investigate:
- Indian broker integration patterns and common API surfaces.
- Broker normalization, routing, and local/self-hosted deployment.
- Boundaries between broker-facing APIs, strategies, and execution.
- Which India-specific product capabilities are application features rather than universal engine semantics.

Question for QuantX: which India-specific integration lessons are useful without making the global core India-specific?

## 3. Comparison dimensions

For each project, record the exact repository revision and inspect relevant source, tests, architecture documentation, and licensing.

| Dimension | Questions |
|---|---|
| Domain model | Are orders, instruments, positions, money, and events vendor-neutral? |
| Market context | How are region, venue, asset class, currency, and contract identity represented? |
| Market rules | Where do sessions, tick/lot constraints, fees, margin, settlement, and corporate actions live? |
| Broker/venue connectors | What is the common contract, and how are capabilities and unsupported operations represented? |
| Market data | How are normalization, timestamps, gaps, provenance, and historical/live differences handled? |
| Execution lifecycle | How are partial fills, cancellations, unknown outcomes, retries, and reconciliation represented? |
| Simulation fidelity | Which semantics are shared across backtest, paper, and live? Which are necessarily different? |
| Risk and capital | How are account state, valuation, margin, and pre-trade restrictions separated from providers? |
| Extensibility | What is a plugin, an adapter, a strategy, a service, or core functionality? |
| Testing | Are there reusable connector contracts, conformance tests, and negative-path tests? |
| Deployment | What runs locally, and what is optional or distributed? |
| Governance | How are compatibility, versions, security, and support commitments communicated? |

## 4. QuantX preliminary hypotheses to verify

These are audit questions, not confirmed defects:

1. `MarketRegion` and `MarketFamily` provide a useful starting classification, but classification alone does not supply a complete market contract.
2. The existing `india/` package and Dhan plugin are useful boundaries; test whether any universal package still imports or relies on India-specific concepts.
3. Common broker contracts exist; verify capability negotiation, conformance testing, and explicit behavior for unsupported operations.
4. Execution safety and recovery are active strengths, but assess whether their abstractions can be reused without weakening fail-closed controls.
5. Research provenance and deterministic backtesting deserve comparison with mature systems before adding broad strategy or AI features.
6. A plugin registry alone does not prove that plugins are safely loadable, compatible, isolated, or production-supported.

## 5. Evidence collection protocol

For every finding, record:

- Reference project and pinned commit/release.
- Source paths and test paths.
- Observed implementation, not inferred intent.
- QuantX equivalent and exact path.
- Difference and practical consequence.
- Proposed action: adopt, adapt, defer, or reject.
- Compatibility and migration risk.
- Test evidence required.
- Confidence: confirmed, probable, or unresolved.

Do not copy a reference project's architecture wholesale. Respect license terms and avoid copying code unless its license and project policy permit it.

## 6. Deliverables

1. Comparative matrix with evidence links.
2. QuantX boundary-gap register ranked by safety and architectural impact.
3. Target architecture diagram that distinguishes current implementation from future packages.
4. Small, ordered change plan with explicit non-goals.
5. Decision record for every material architectural change.

## 7. Exit criteria

The comparative audit is complete only when each high-priority conclusion is backed by source evidence, the current QuantX behavior is verified, conflicting patterns are explained, and the recommended changes can be implemented incrementally without broad unproven refactors.


## 8. Required Indian-market and broker/API coverage

OpenAlgo is a starting reference, not a sufficient survey of the Indian ecosystem. Add an evidence-based review of relevant projects and official integration surfaces, selecting examples based on current maintenance, documented APIs, license, tests, and practical fit. At minimum, evaluate:

- OpenAlgo — self-hosted Indian multi-broker control plane and broker-normalization patterns.
- Official broker APIs: Zerodha Kite Connect, Upstox API, Dhan HQ API, Angel One SmartAPI, Fyers API, and Shoonya API, where current documentation and access terms permit meaningful evaluation.
- Other actively maintained Indian open-source broker adapters or gateways discovered during research; verify repository identity, license, recent activity, and actual implementation before inclusion.
- Global engine/connector references: LEAN, NautilusTrader, Hummingbot, CCXT, Backtrader/VectorBT, Freqtrade, and Jesse, comparing each only on capabilities relevant to its purpose.

This is a research checklist, not an endorsement, compatibility claim, or promise to implement every broker. Verify official API documentation and repository evidence at audit time; record retrieval date and pinned repository revision.

## 9. Mandatory comparison output

For each reference, record: project/API and official URL; license and maintenance signal; repository revision or documentation version and audit date; purpose and applicable asset classes/venues; relevant architecture boundaries; actual connector/order/data capabilities and unsupported cases; tests, sandbox/paper support, and failure/recovery coverage; authentication/security and rate-limit considerations; QuantX equivalent with exact source/test paths or explicit absence; finding severity, confidence, recommendation (adopt/adapt/defer/reject), and evidence.

Do not compare raw feature counts as if projects have identical purposes. Separate product breadth from engine correctness, connector breadth from tested reliability, and documentation claims from source-confirmed behavior.

## 10. Required QuantX conformance checks

Inspect actual source and tests for: (1) import/dependency direction; (2) canonical instrument identity and derivative metadata; (3) explicit money, quantity, fee, margin, funding, settlement, and corporate-action units; (4) timezone-aware timestamps, calendars, sessions, holidays, data gaps, and trusted-clock behavior; (5) partial fills, cancel/replace, rejects, unknown submission outcomes, idempotency, reconciliation, and restart recovery; (6) capability negotiation and fail-closed handling of unsupported operations; (7) point-in-time data, look-ahead/survivorship bias, transaction costs, slippage, deterministic replay, and research/live parity limits; (8) account/market isolation, risk freshness, durable kill-switch/trading gates, startup readiness, and LIVE eligibility; (9) persistence, audit trail, observability, secrets, and operator recovery; and (10) licensing, compatibility/versioning, and support claims.

Each check must produce pass/partial/fail/not assessed, evidence paths, test evidence, risk, and next action. Do not mark a check passed based on an enum, interface name, or README statement alone.
