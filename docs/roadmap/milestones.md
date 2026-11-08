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
**Status:** **Complete** against the canonical M4 exit criterion, reconciled on `main` after PR #325. M4.1 deterministic Python strategy-to-paper rehearsal is merged in PR #218 (validated head `d99c12f3ae051f992722bee2bc8ea3253032fdc8`; merge commit `a0bf101b6f6bb87d11460cefb199932a768d6335`). QX-09/#197 and QX-08/#196 are complete; the first Flow path and offline execution parity are complete in PRs #317, #320, #321 and #324.
**Exit:** **MET** — Python strategies and a first Flow path compile to the same runtime semantics. Evidence includes the Python/Flow `StrategyRuntime` semantic-result parity test in PR #321 and the offline deployment/preparation/risk/policy/PAPER/BACKTEST integration tests in PR #324. Exact candidate-SHA local validation is recorded in those PRs; it is operator-reported local evidence, not hosted CI.
**Build order:** the historical prerequisite ordering is complete: issue #197's market-pack pre-trade-check pipeline merged in PR #221; issue #196's StrategyContext/callback implementation and T1–T8/G1–G3 acceptance closeout merged in PRs #224, #226, #229, #232 and #234. Do not reopen completed slices absent a new reproduced defect. Broader visual Flow UI/persistence, scheduling, webhooks/external signals, AI/cloud and LIVE capabilities remain future platform work, not M4 exit gates.

## M5 — Control Plane
**Exit:** REST/WS, strategy lifecycle, monitoring and audit are usable.

## M6 — Ecosystem
**Exit:** plugin contracts are stable enough for third-party development and optional AI/analytics integrations.
