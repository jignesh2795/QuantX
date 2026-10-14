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

Regression coverage asserts that the receipt remains durable after injected completion failure, and the current full suite passes at the 634-test checkpoint.

## Correctness finding: broker-returned UNKNOWN receipt must remain pending — resolved and validated

A broker adapter can legitimately return an `ExecutionReceipt` whose outcome is `UNKNOWN` when transport failure or an indeterminate broker response prevents an authoritative submission result. The canonical LIVE orchestrator now treats such a receipt as non-authoritative: it returns `UNKNOWN`, does not persist the receipt as completion evidence, and leaves the already-committed durable idempotency reservation PENDING for reconciliation. A repeated execution attempt therefore does not resubmit the order.

This closes the Dhan-relevant transport-failure path where an adapter converts an exception into an `UNKNOWN` receipt. Regression coverage verifies the pending reservation, absence of a completion receipt, and no-resubmit behavior. The current full suite passes at the 635-test checkpoint.

## Correctness finding: secondary LIVE dispatch bypass — resolved and validated

`ExecutionDispatcher` previously submitted LIVE requests directly to `LiveExecutionPort`, bypassing durable idempotency, persistence, and the trading gate. Its LIVE branch now fails loudly and requires callers to use `ExecutionOrchestrator` with durable `UnitOfWork`. The generic `BrokerExecutionAdapter` also rejects direct LIVE use so lower-level adapter wiring cannot become an unintended execution entry point.

Regression coverage verifies that these direct LIVE routes do not call the broker adapter, and the current full suite passes at the 634-test checkpoint.

## Correctness finding: LIVE persistence bypass — resolved and validated

The canonical `ExecutionOrchestrator` LIVE path previously allowed execution without a `UnitOfWork`, falling back to process-local idempotency. That meant an uncertain LIVE submission could lose its pending reservation on process restart and become eligible for duplicate broker submission. LIVE now fails closed when a `UnitOfWork` is not configured and uses the two-scope transactional path exclusively.

Paper, shadow, and replay execution remain usable without persistent storage. The current validated test checkpoint is `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c` with 635 passed, 0 failed, 0 errors, 0 skipped; `5817ce0f9cb2103f9ba05abfefa7495c5f2ec342` is import-only cleanup after that validation.

## Correctness finding: projected continuation margin/risk composition — resolved and validated

`PaperSession._check_continuation_projection()` previously referenced a nonexistent public `MarginLedger.reservations` attribute. The margin ledger now exposes an immutable tuple snapshot of reservations, and the projected outstanding-margin aggregation is explicitly seeded with `Decimal("0")` for deterministic typing. The existing position-margin continuation regression now also composes `MarginLedger` with `PostTradeRiskEnforcer`, covering the previously untested path.

The three-file fix is historical; the branch now has 635 passing tests, with the latest fully executed suite at `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c`.

## Correctness finding: durable LIVE trading-gate state — resolved and validated

LIVE execution now requires an explicitly configured durable `TradingGate`. SQLite-backed gate state persists across process recreation, including block/enable transitions, and process-local gates are rejected for LIVE. Schema v2 creates and migrates the durable gate state table. That hardening was introduced and validated earlier at `82a0a2a367d7131c18e3dd9491b7e83fd1077c0a`; the latest branch-wide test evidence is 635 passed at `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c`.

## Correctness finding: durable pending LIVE execution context — resolved and validated

Pending LIVE idempotency reservations now persist a versioned execution-context projection sufficient to reconstruct a recovery request after restart. SQLite stores and enumerates pending contexts without resubmission; reconciliation resolves the reservation by persisting authoritative evidence, while the pending enumeration correctly becomes empty after resolution. Round-trip, restart, LIVE composition, and runner coverage were established in the earlier 625-test checkpoint; they remain covered by the latest 635-test suite.

## Correctness finding: durable gate refresh across running instances — resolved and validated

A durable trading gate now refreshes persisted state when queried, so separate already-running instances share operator block/enable changes instead of retaining stale process-local state. Missing durable state is fail-closed. Regression coverage verifies cross-instance refresh; the earlier green checkpoint was `82a0a2a367d7131c18e3dd9491b7e83fd1077c0a`, and the latest 635-test suite remains green.

## Correctness finding: legacy LIVE transaction-coordinator bypass — resolved and validated

The legacy `ExecutionTransactionCoordinator` no longer creates a new LIVE idempotency reservation. For LIVE requests it performs read-only idempotency inspection: existing completed state may be returned, pending state remains reconciliation-only, and a fresh LIVE request is blocked before submission. This preserves reconciliation callers without exposing a standalone LIVE submission path. The current validated checkpoint is `5817ce0f9cb2103f9ba05abfefa7495c5f2ec342` with 635 passed, 0 failed, 0 errors, 0 skipped.

## Correctness finding: boot-time pending LIVE recovery orchestration — implemented and validated

`PendingExecutionRecoveryRunner` enumerates persisted pending LIVE contexts, reconstructs recovery requests, resolves a provider using the persisted request identity, invokes reconciliation, and records a deterministic per-context result. It contains no broker-submit operation. Provider/reconciliation failures are isolated to the affected context so other pending contexts can still be processed.

Regression coverage includes simulated process restart, successful resolution through reconciliation, failure isolation, pending-state preservation, and the invariant that reconciliation does not expose a submit/broker execution parameter. The current full suite is 635 passed, 0 failed, 0 errors, 0 skipped.

This remains a one-shot application hook, not a startup daemon. ProductionRuntime now composes the durable store, recovery resolver, runner, and ApplicationRuntime; the host is responsible for explicitly calling start() before serving execution.

## Correctness finding: LIVE startup readiness and gate check-to-submit race — addressed on the current hardening branch

A subsequent adversarial review identified two control-path gaps not represented by the historical 635-test checkpoint above.

First, `ExecutionOrchestrator` previously enforced a durable trading gate but did not require the recovery-backed `ApplicationRuntime` to have completed startup recovery. LIVE execution could therefore be reached before the explicit boot-time recovery lifecycle had run. The orchestrator now requires a supplied `ApplicationRuntime` and rejects LIVE execution until it is started.

Second, the LIVE path had a check-to-submit TOCTOU window: `TradingGate.allow()` could return enabled and the gate could then be blocked before `broker.submit()`. The trading gate now provides a submission permit that re-checks state and holds authorization across durable idempotency reservation and the broker submission. The permit is acquired before reservation, so a denied gate never leaves a new pending reservation behind.

These changes preserve the existing two-scope database rule: no database transaction spans the broker call. The gate permit is an independent in-process synchronization boundary.

Regression coverage on the hardening branch adds unstarted-runtime rejection, final authorization under a blocked gate, and the concurrent block/submission ordering invariant. Independent local full-suite validation was completed during the PR review: Claude's sandbox run reached 813 passed tests after the affected fixtures were aligned with the new runtime/evidence contracts. The merged mainline contains those equivalent test fixes plus an additional explicit unscoped negative-case correction. GitHub Actions is not used as validation evidence while billing is disabled.

## Remaining recovery-boundary questions

The focused adversarial implementation gaps identified for pending recovery are now covered by the current validated checkpoint: malformed persistence is isolated, default all-required evidence can resolve, concurrent resolution is guarded by durable idempotency, broker-order scope is enforced, reconciliation exposes no broker-submit capability, and broker-returned UNKNOWN LIVE receipts remain pending rather than being treated as authoritative completion.

## Production startup composition — implemented and validated

The concrete production startup composition for pending LIVE recovery is implemented without new registries, routers, or reconciliation frameworks. `RecoveryEndpointResolver` resolves a recovery evidence provider from the persisted execution identity using only the existing `AccountConnectionRegistry`: the persisted broker connection id is looked up exactly, then account equality, enabled state, and optional expected-broker identity are enforced before a provider is built. There is no default-account or default-connection fallback; anything unresolvable fails closed and the reservation stays pending.

`DhanRecoveryEvidenceProvider` (in `plugins/dhan/recovery.py`) implements the canonical `ReconciliationEvidenceProvider` contract over a bound Dhan adapter using only read paths (`order_detail`, `account_state`, `position_states`). Dhan order detail is mapped onto `OrderObservation` with unrecognized or expired broker states mapped to UNKNOWN rather than inventing lifecycle transitions. The provider is bound to one account, connection, order, correlation, and quantity; every fetch verifies its arguments against that binding. `build_application_runtime()` wires the durable `UnitOfWork`, registry, evidence factory, optional local providers, runner, and one-shot `ApplicationRuntime.start()` together with no broker-submit capability anywhere in the path.

Regression coverage proves exact endpoint resolution, wrong-account/connection/broker rejection, multi-account selection by persisted connection identity, zero broker submissions during recovery, authoritative resolution through existing reconciliation, non-definitive evidence remaining pending, per-context failure isolation, one-shot startup semantics, and process-recreation recovery against the same durable store. No real broker end-to-end execution is claimed; recovery is validated with the in-memory Dhan transport and SQLite file databases, and no GitHub CI run is claimed as evidence.

## Final adversarial LIVE/broker reachability audit — completed

The final boundary audit found no alternate LIVE submission path in the current stack.

- ExecutionOrchestrator._execute_live_transactional() remains the sole application-owned LIVE submission path and requires durable UnitOfWork plus an explicitly configured durable TradingGate.
- ExecutionDispatcher rejects LIVE before touching LiveExecutionPort; BrokerExecutionAdapter also rejects direct LIVE use.
- ExecutionTransactionCoordinator is LIVE inspection-only: it may read completed idempotency/receipt state or return UNKNOWN/BLOCKED, but it never reserves or calls submission.
- ExecutionContinuationService routes dispatch through ExecutionDispatcher; therefore continuation cannot bypass the LIVE boundary.
- Dhan's concrete adapter is the only broker submission implementation in the current plugin surface audited here. Recovery uses only order_detail, account_state, and position_states; the Dhan transport submit/cancel methods are not exposed by the recovery provider.
- RecoveryEndpointResolver binds recovery to the exact persisted account/connection identity and rejects missing, disabled, mismatched, or drifted registrations.
- No new runtime/router/registry layer is justified by this audit, and no credentials or vendor transport construction belongs in application/domain code.

Validation evidence remains separate from CI evidence: the branch has the externally reported 665-test OpenCode validation, while the corresponding GitHub Actions run had failed without retrievable job logs and was re-queued for verification. No production-broker end-to-end result is being inferred from that run.
## Next action

Do not restructure these modules further. Treat the execution/recovery boundary as frozen unless a new concrete invariant violation is demonstrated. The remaining work is stack integration and host/deployment work; UI, AI, and a broad broker matrix should follow only after this foundation is integrated cleanly.
