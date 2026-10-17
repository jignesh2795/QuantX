---
name: quantx-risk-policy
description: Use when working on QuantX risk or kill-switch behavior — pre-trade limits, exposure/drawdown/daily-loss, margin, approval-required, trading-gate trips, post-trade breach. Maps existing implemented contracts; never adds new enforcement. Keywords: risk, limits, drawdown, margin, kill switch, gate, approval, breach, blocked.
metadata:
  quantx/role: risk
---

# QuantX Risk & Policy Contracts

This skill **maps and audits the implemented risk contracts**. It is not a second policy authority: runtime enforcement exists only in `src/quantx`, and changing it requires source changes, a control-path safety review (`quantx-core-governance`), tests, and validation. Never encode a competing rule in a plan, prompt, config, or plugin that silently diverges from the contracts below.

- Canonical ordered control path: `docs/architecture/control-and-safety-path.md`
- Live safety gap tracker: `docs/architecture/56-live-execution-safety-audit-and-priority.md` (P0.2/P0.3 and P1 items remain open)
- Submission, gate-wiring, idempotency, recovery detail: `quantx-execution` skill

## Decision vocabulary (use the real code values)

| Layer | Type | Values |
|---|---|---|
| Pre-trade risk | `RiskDecision` (`domain/risk.py`) | `APPROVE` / `REJECT` / `APPROVAL_REQUIRED` |
| Constraint checks | `ConstraintResult` (`domain/constraints.py`) | `PASS` / `WARN` / `REJECT` / `REQUIRES_APPROVAL` |
| Execution policy | `PolicyDecision` (`domain/policy.py`) | `APPROVE` / `REJECT` / `APPROVAL_REQUIRED` |
| Preconditions / dispatch | `PreconditionVerdict`, `ExecutionDispatchStatus` | `READY` / `BLOCKED` / `UNKNOWN` etc. |
| Gate state | `TradingGateState` | `enabled: bool` + reason |

Mapping discipline: "PASS/BLOCK" in conversation maps to these exact enums — do not invent new outcome names in code or docs. `UNKNOWN` exists only at precondition/dispatch/receipt layers: it is **never approval**, never advances critical state, and never becomes a retry.

## Layer map

| # | Layer | Owner | Enforces |
|---|---|---|---|
| 1 | Pre-trade base | `PreTradeRiskEngine.evaluate` (`domain/risk.py`) | execution context present; capital currency + available margin (`evaluate_capital`); determinable order notional; broker constraints (min value/qty/margin); approval flag |
| 2 | Pre-trade limits (R1-A) | `PreTradeRiskEngine.evaluate_with_limits` | order notional, projected position/portfolio exposure, instrument concentration, realized daily loss, drawdown, snapshot freshness, margin, all against caller-supplied `RiskLimits` + `RiskSnapshot` |
| 3 | Execution policy | `ExecutionPolicyEngine` (`domain/policy.py`) | LIVE requires `live_trading_enabled` + `CREATE_LIVE_ORDER`/`EXECUTE_LIVE`/`ACCESS_BROKER` capabilities; manual approval flow |
| 4 | Session guard | `SessionExecutionGuard` (`execution/session_guard.py`) | non-REPLAY modes blocked when session closed |
| 5 | Trading gate + reservation | `execution/trading_gate.py` + `application/execution.py` | no submit without permit + durable reservation; `admit_submission()` linearization point |
| 6 | Post-trade enforcement | `execution/post_trade_risk.py`, `post_trade_enforcement.py` | account limits after state change; breach trips the runtime gate |
| 7 | Margin requirement | `PositionMarginPolicy` port (`execution/margin_policy.py`) | core assumes no leverage formula; adapter supplies required post-trade margin |

## Pre-trade rules that must not be softened

- Missing/undeterminable inputs reject: no execution context, unknown order value, currency mismatch, insufficient available margin, missing broker constraint values.
- `evaluate_with_limits` requires a tz-aware `evaluated_at` and a non-None `RiskSnapshot`; otherwise `RISK_SNAPSHOT_MISSING` / `RISK_VALUE_INVALID` → `REJECT`.
- Freshness is explicit: snapshot age vs `limits.max_snapshot_age`; future-dated snapshot → `RISK_STATE_INCONSISTENT`. The engine reads no clocks and no brokers.
- Numbers: bool, float, str, and non-finite Decimals are invalid, never coerced (`_risk_number`). Missing snapshot fields needed by an enabled check fail closed — **unknown is not zero**.
- Signed exposure: BUY adds, SELL reduces (`_signed_notional`); projected = current + signed, compared by absolute value. Concentration uses `|instrument + signed| / |portfolio + signed|`; zero denominator → `RISK_STATE_INCONSISTENT`.
- Daily loss counts **realized** `daily_pnl` only; the proposed order is never treated as a realized loss. Drawdown = `(high_water_mark − equity) / high_water_mark`.
- Stable reason codes in evaluation order (grep them in `domain/risk.py`): `RISK_SNAPSHOT_MISSING`, `RISK_SNAPSHOT_STALE`, `RISK_STATE_INCONSISTENT`, `RISK_VALUE_INVALID`, `ORDER_NOTIONAL_LIMIT_EXCEEDED`, `POSITION_EXPOSURE_LIMIT_EXCEEDED`, `PORTFOLIO_EXPOSURE_LIMIT_EXCEEDED`, `INSTRUMENT_CONCENTRATION_LIMIT_EXCEEDED`, `DAILY_LOSS_LIMIT_EXCEEDED`, `DRAWDOWN_LIMIT_EXCEEDED`, `MARGIN_INSUFFICIENT`.
- `RiskLimits` fields default to `None` = check disabled. Construction alone is **not** a non-open risk policy (audit P1 — no mandatory LIVE composition yet).

## Post-trade enforcement

- `PostTradeRiskEnforcer.evaluate/evaluate_projected_limits` checks margin utilization, gross exposure, open positions, single-position exposure, daily loss; on breach it calls `gate.block("; ".join(reasons))`.
- A gate trip stops **new submissions only**: it never cancels, flattens, or mutates existing orders. No `reduce-only`/`flatten`/`cancel-all` capability exists in `src/` (audit finding) — do not describe or implement compensating trades as risk handling.
- Wired today in `execution/paper_session.py` (cash/margin ledger sessions). LIVE composition does not assemble it yet.

## Trading-gate integration (risk view)

- Disarmed default (`default_enabled=False`) + persisted; a failed `block()`/`enable()` persist latches a domain-shared fail-closed fault; queries and submit admission then report blocked without reloading stale enabled state; only a successfully persisted command clears it. Process-local latch does not survive crash.
- `submission_permit()` covers the gate check + durable reservation only; `admit_submission()` is the last check before `broker.submit()`. Denied admission → `BLOCKED`, reservation stays `PENDING` (never submitted, never uncertain, never auto-retried). An admitted in-flight call runs to its genuine outcome.
- No path may bypass the gate + approved dispatcher. Full contract lives in the `quantx-execution` skill.

## Honest wiring status (verified at this base)

- Base risk + policy: wired in `StrategyExecutionPreparer` (`strategy/execution.py`) and `DeterministicBacktestService` (`application/backtest.py`).
- LIVE limits engine: implemented and tested (`tests/unit/application/test_live_risk.py`) but activation is **caller-injected** via `ExecutionOrchestrator(live_risk_evaluator=...)`; absent evaluator or absent `session_guard` skips that layer; evaluator exception/`non-APPROVE` → `BLOCKED`.
- Approval is not yet bound to request fingerprint/snapshot identity (audit P1) — `ApprovedExecutionRequest.__post_init__` only verifies the enum, LIVE connection, and approved policy.
- `ApplicationRuntime.start()` currently marks the runtime started even when the recovery report contains unresolved/failed records (audit P0.2, issue #240). Do not claim LIVE readiness from a green start.
- P0.1 durable kill-switch remediation is merged (PR #243: commits `a75ad3c`, `9e961d0`, `f2db0d8`, skills sync `7dd4640`); the P0.1 narrative inside doc 56 predates that fix.

## Adversarial cases to check on every risk change

| Scenario | Required behavior |
|---|---|
| Projected limit breach (position/portfolio/concentration/loss/drawdown) | `REJECT` with reason codes; no reservation, no side effects |
| Missing, stale, or future-dated snapshot; missing exposure/margin field | fail closed (`REJECT`), never default to zero or last-known |
| Malformed numbers (bool/float/str/NaN/Infinity) | invalid → fail closed, no coercion |
| Concurrent submissions vs `block()` | linearization at `admit_submission()`; not-yet-admitted denied; admitted run to genuine outcome; never reported as cancelled |
| Failed gate persist | domain-shared fault latch; queries/admission blocked; command paths raise loudly |
| Concurrent recovery of one reservation | resolved at most once; per-context failure isolation |
| Broker `UNKNOWN` receipt | durable `PENDING`, no idempotency completion, reconciliation required, no auto-retry |
| Post-trade breach | gate trips; existing orders untouched; reasons preserved in gate state |

## Operator / escalation rules

- Breach reasons survive in `gate.state().reason`. Blocking is never cleared implicitly; only a successfully persisted `enable()` restores submission.
- Pending LIVE reservations resolve through `application/operator_resolution.py` and `application/not_found_policy.py`; recovery (`application/pending_recovery.py`) never submits broker orders.
- Escalate — do not paper over — any change that could weaken: fail-closed snapshot handling, the gate admission boundary, UNKNOWN durability, or realized-vs-unrealized P&L semantics.

## Testing pointers

```powershell
uv run pytest tests/unit/application/test_live_risk.py -q
uv run pytest tests/unit/domain/test_risk.py tests/unit/execution/test_post_trade_risk.py -q
uv run pytest tests/unit/execution/test_post_trade_enforcement.py tests/unit/execution/test_trading_gate.py -q
uv run pytest tests/unit/persistence/test_sqlite_trading_gate.py -q
```

## Related skills

- `quantx-execution` — submission boundary, idempotency, reconciliation, recovery
- `quantx-simulation-accounting` — ledgers, valuation, P&L, charges
- `quantx-india-market` — sessions, price bands, India market checks
- `quantx-core-governance` — control-path safety review questions
