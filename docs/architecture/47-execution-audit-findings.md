# Execution Audit Findings

## Current decisions

The execution package is intentionally not split into folders merely for visual symmetry. A module remains standalone when it has one cohesive responsibility.

### Canonical modules

- `ports.py`: execution port for already-approved requests.
- `market_ports.py`: execution port that explicitly requires a point-in-time `MarketSnapshot`.
- `market_data.py`: observable market snapshot contract.
- `models.py`: deterministic fill/slippage model contracts.
- `paper.py`: paper/shadow/replay execution engine.
- `paper_session.py`: end-to-end paper orchestration across execution, accounting and valuation.
- `accounting.py`: fill-to-position accounting.
- `valuation.py`: position mark-to-market valuation.
- `portfolio_valuation.py`: portfolio-level valuation orchestration.
- `order_lifecycle.py`: order state machine.
- `idempotency/`, `preconditions/`, `receipts/`, `transactions/`: dedicated execution safety/orchestration boundaries.

## `ports.py` vs `market_ports.py`

These are intentionally different contracts, not duplicates.

`ExecutionPort.execute(request)` represents an execution implementation that owns or obtains its required execution inputs.

`MarketDataExecutionPort.execute(request, snapshot=...)` explicitly requires a caller-supplied point-in-time market snapshot. This is useful for deterministic replay/paper components and prevents hidden market-data access.

Do not merge these merely to reduce file count.

## `paper.py` vs `paper_session.py`

These are also intentionally different responsibilities.

- `PaperExecutionEngine` determines whether and how an approved order fills from supplied market data and execution models.
- `PaperSession` orchestrates execution -> fill accounting -> valuation.

Do not merge them into one large module.

## Correctness finding: simulation timing and fees — resolved

`PaperSimulationProfile` latency is now applied to the simulated fill and execution-receipt timestamps. The engine does not shift the observed market price into the future because doing so would require unavailable future market data.

Simulation fees are calculated on the executed fill and carried on `ExecutionReceipt`. `PaperSession` now consumes that receipt fee by default when applying fills to accounting; an explicit `fee` argument remains available as an override.

## Correctness finding: instrument metadata — resolved

`PaperSession` resolves the canonical `Instrument` through `InstrumentRegistry` and rejects execution when authoritative metadata is unavailable or inconsistent with the request. It does not manufacture fallback asset class, currency, tick size, lot size, or multiplier values.

## Correctness finding: deterministic backtest strategy boundary — resolved

`DeterministicBacktestService` accepts both the canonical `StrategyEvaluationService` path and a direct callable strategy seam. The direct callable path now enforces the same signal/intent instrument, strategy identity, BUY/SELL direction, and replay-timestamp invariants before risk or execution. This prevents a custom replay strategy from bypassing the execution-facing strategy contract.

## Correctness finding: LIVE receipt durability on completion failure — resolved and validated

`ExecutionOrchestrator._execute_live_transactional()` previously rolled back the receipt insert when idempotency completion failed. That could erase the only durable proof of a successful broker submission while leaving the reservation PENDING. The completion-failure path now preserves and commits the receipt while leaving idempotency unresolved for reconciliation.

Regression coverage asserts that the receipt remains durable after injected completion failure, and the full 614-test suite passes at the current green checkpoint.

## Correctness finding: secondary LIVE dispatch bypass — resolved and validated

`ExecutionDispatcher` previously submitted LIVE requests directly to `LiveExecutionPort`, bypassing durable idempotency, persistence, and the trading gate. Its LIVE branch now fails loudly and requires callers to use `ExecutionOrchestrator` with durable `UnitOfWork`. The generic `BrokerExecutionAdapter` also rejects direct LIVE use so lower-level adapter wiring cannot become an unintended execution entry point.

Regression coverage verifies that these direct LIVE routes do not call the broker adapter, and the full 614-test suite passes at the current green checkpoint.

## Correctness finding: LIVE persistence bypass — resolved and validated

The canonical `ExecutionOrchestrator` LIVE path previously allowed execution without a `UnitOfWork`, falling back to process-local idempotency. That meant an uncertain LIVE submission could lose its pending reservation on process restart and become eligible for duplicate broker submission. LIVE now fails closed when a `UnitOfWork` is not configured and uses the two-scope transactional path exclusively.

Paper, shadow, and replay execution remain usable without persistent storage. The current green checkpoint is `d9f54765c0fc6c7ae975750592aedaf9253ebb8b` with 614 passed, 0 failed, 0 errors, 0 skipped.

## Correctness finding: projected continuation margin/risk composition — fixed, validation pending

`PaperSession._check_continuation_projection()` previously referenced a nonexistent public `MarginLedger.reservations` attribute. The margin ledger now exposes an immutable tuple snapshot of reservations, and the projected outstanding-margin aggregation is explicitly seeded with `Decimal("0")` for deterministic typing. The existing position-margin continuation regression now also composes `MarginLedger` with `PostTradeRiskEnforcer`, covering the previously untested path.

The three-file fix is committed after the `746ed9d37d0922f4eff32822a0f485a31d71e10d` green baseline and was validated as part of the subsequent 612-test green run at `d706dc7`.

## Next action

Do not restructure these modules further. With the current validation green, the next focused audit is durable kill-switch state and the request context needed for automatic pending recovery; then run an adversarial end-to-end LIVE entry-point audit with Claude before considering the execution boundary stable.

The canonical `ExecutionOrchestrator` LIVE path previously allowed execution without a `UnitOfWork`, falling back to process-local idempotency. That meant an uncertain LIVE submission could lose its pending reservation on process restart and become eligible for duplicate broker submission. LIVE now fails closed when a `UnitOfWork` is not configured and uses the two-scope transactional path exclusively.

Paper, shadow, and replay execution remain usable without persistent storage.
