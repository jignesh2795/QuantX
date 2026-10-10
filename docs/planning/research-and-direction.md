# QuantX Research & Direction Notes

This document captures the research, comparisons, and planning discussions used to shape QuantX direction.

It is intentionally kept on a planning branch so it does not interfere with the main implementation track.

## 1. Project Context

QuantX is an open-source, modular, event-driven trading infrastructure focused on Indian markets (equities and F&O), with a venue-neutral core that can support additional markets later.

Current implementation priority (as of the STATUS baseline):

- Execution integrity
- Reconciliation and recovery safety
- LIVE control hardening
- Clear production host composition

UI, AI, and broad broker matrix work remain later concerns.

## 2. Architecture References

Key external projects studied:

| Project | Role as reference |
|---------|-------------------|
| **OpenAlgo** | Indian multi-broker control plane and practical self-hosted platform |
| **NautilusTrader** | Event-driven, deterministic, ports-and-adapters engine design |
| **QuantConnect LEAN** | Mature research-to-live parity and modular plugin architecture |
| **Hummingbot** | Connector / plugin patterns |
| **Backtrader / VectorBT** | Research and backtesting workflow patterns |
| **Freqtrade / Jesse** | Strategy and automation workflow references |

### Hybrid architecture insight

A practical high-quality pattern for Indian markets is:

- Strong Indian broker connectivity layer (OpenAlgo-style or native adapters)
- High-integrity event-driven core (NautilusTrader / LEAN-inspired)
- Specialized research tools (VectorBT / Backtrader) for early strategy work

QuantX is intentionally building the clean core rather than becoming only a broker gateway.

## 3. OpenAlgo Comparison (as of Oct 2026)

| Dimension | OpenAlgo | QuantX direction |
|-----------|----------|------------------|
| Strength | Breadth, multi-broker coverage, usability, ecosystem | Depth, execution integrity, domain model, recovery |
| Architecture | Flask + React control plane with broker plugins | Event-driven + domain-driven + ports-and-adapters |
| Maturity | High usage (approx 2.8k stars, 100k+ downloads, active community) | Early (v0.1 foundations) |
| License | AGPL-3.0 | More permissive stance preferred for flexibility |
| Best fit | Fast multi-broker automation | Correctness-focused engine that others can build on |

OpenAlgo validates demand for open-source Indian algo infrastructure.
QuantX differentiates on engine quality and safety rather than trying to match broker count early.

## 4. Improvement Priorities

Ordered for a correctness-first, flexible project:

1. Finish and harden LIVE recovery + trading-gate path
2. Stabilize production host composition
3. Keep architecture boundaries strict (core vs adapters/plugins)
4. Design a clean multi-broker adapter model (without rushing breadth)
5. Strengthen research/backtest realism and fidelity reporting
6. Improve onboarding, examples, and documentation of guarantees

## 5. Flexibility Principle

QuantX is not locked to any single user type.

Valid uses include:

- Research / backtesting
- Paper trading
- Live execution
- Embedding inside other systems
- Building specialized plugins or products later

Opinionated or audience-specific features should live outside the core as:

- Plugins
- Adapters
- Separate projects

## 6. Non-Monetization Stance (current)

At the present stage there is no monetization plan.

Implications:

- Keep the core fully open and high quality
- Optimize for clarity, correctness, and composability
- Attract serious users and potential contributors through architecture quality
- Defer commercial packaging, hosted offerings, and opinionated product surfaces

Future specialized projects (plugins or separate systems) can explore different focuses without forcing the core to become product-specific.

## 7. Near-Term Guidance

When deciding what to build next, prefer work that:

- Strengthens execution safety and recovery
- Clarifies contracts and guarantees
- Improves adapter boundaries
- Makes the engine easier to understand and extend

Avoid early expansion into broad UI, many brokers, or audience-locked workflows until the core is stable.
