# QuantX Decision Gates

## Gate 0 — Architecture

No production implementation until domain boundaries, dependency rules, plugin model and execution semantics are documented.

## Gate 1 — Trading core

Core lifecycle works with the paper broker and deterministic simulation.

## Gate 2 — Indian domain

Equity/futures/options contracts, sessions, margin and charges are represented without broker-specific branching.

## Gate 3 — Adapter ecosystem

At least one broker and one data adapter pass reusable contract tests.

## Gate 4 — Research/live symmetry

Backtest, sandbox, paper and live share domain semantics and can be compared/replayed.

## Gate 5 — Platform

REST/WS, strategy lifecycle, monitoring, audit and Action Center are stable.

## Gate 6 — Ecosystem

Plugin API, manifests, capability negotiation, compatibility checks and documentation are stable enough for external contributors.
