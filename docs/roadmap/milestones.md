# QuantX Milestones

## M0 — Architecture
**Exit:** architecture reviewed; contracts and dependency rules documented.

## M1 — Indian Trading Foundation
**Exit:** domain supports equity/futures/options contracts and core trading lifecycle.

## M2 — Broker/Data Platform
**Exit:** paper broker plus initial production broker/data adapters pass common contract tests.

## M3 — Simulation and Research
**Exit:** backtest/paper semantics converge and core research workflow is reproducible.

## M4 — Strategy Platform
**Status:** Active. M4.1 deterministic strategy-to-paper rehearsal merged in PR #218 (validated head `d99c12f3ae051f992722bee2bc8ea3253032fdc8`; merge commit `a0bf101b6f6bb87d11460cefb199932a768d6335`). This first vertical does not complete M4 overall.
**Exit:** Python strategies and a first Flow path compile to the same runtime semantics.
**Build order:** issue #197's market-pack pre-trade-check pipeline precedes broader StrategyContext/callback work tracked in #196.

## M5 — Control Plane
**Exit:** REST/WS, strategy lifecycle, monitoring and audit are usable.

## M6 — Ecosystem
**Exit:** plugin contracts are stable enough for third-party development and optional AI/analytics integrations.
