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
