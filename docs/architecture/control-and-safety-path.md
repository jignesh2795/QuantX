# Control and Safety Path

This document describes the intended ordered control path for QuantX execution.

It is adapted from QuantumTrade's multi-layer safety thinking, rewritten for QuantX's architecture: execution integrity, recovery, trading gates, fail-closed LIVE, ports-and-adapters, and Indian-market-aware domain modeling.

**Status:** Draft / target architecture with implemented anchors.  
Where behavior is already implemented (per `docs/STATUS.md`), it is marked. Where partial, that is stated explicitly.

---

## 1. Purpose

Make the control path obvious and testable:

- What must happen before a broker submit is allowed
- What is persisted and why
- What happens on uncertain or failed outcomes
- What recovery is allowed to do — and forbidden from doing

**Governing principle:** Prefer fail-closed behavior and authoritative evidence over inference.

---

## 2. Ordered path (canonical)

```
Strategy / application intent
        |
        v
[1] Domain validation
    - Instrument, side, quantity, order type
    - Account / connection identity
    - Capability checks (adapter supports the operation)
        |
        v
[2] Pre-trade risk / policy checks          (partial today)
    - Stateless or narrowly scoped decisions
    - Reject without side effects when possible
        |
        v
[3] Trading gate + reservation               (implemented direction)
    - Durable trading-gate authorization
    - Idempotency / pending LIVE reservation context
    - Runtime must be recovery-backed and started where required
        |
        v
[4] Broker submit (adapter boundary only)
    - Approved dispatcher/adapter path only
    - Direct LIVE bypasses blocked
        |
        v
[5] Receipt capture
    - Durable execution receipt
    - Retain receipt even when idempotency completion is uncertain
    - Broker UNKNOWN remains durably PENDING
        |
        v
[6] Fill / continuation handling
    - Partial-fill continuation and lineage
    - Claims validated against authoritative receipt identity
        |
        v
[7] Reconciliation and recovery              (strong focus)
    - Reconstruct from authoritative evidence
    - Isolate malformed contexts
    - At-most-once resolution of pending reservations
    - Recovery runners do not submit to brokers
        |
        v
[8] Portfolio / position state update
    - Driven by accepted evidence only
```

---

## 3. Layer detail

### 3.1 Domain validation

**Intent:** Reject invalid or unsupported intents before any reservation or submit.

Should cover:

- Structural validity of the intent (fields, types, bounds)
- Instrument and market-segment rules relevant to the domain (including F&O-aware rules where applicable)
- Account and connection identity binding
- Capability checks (does this adapter/broker support this order type, product, or path?)

**Rule:** Adapters must not be the first place basic identity and capability rules are enforced.

### 3.2 Pre-trade risk / policy checks

**Intent:** Explicit, testable risk decisions without becoming a full retail "safety product."

Target characteristics:

- Prefer pure/stateless checks where possible
- Clear approve/reject outcomes with reasons
- No hidden mutation of portfolio state on reject

**Current state:** Partial. Trading gates and domain foundations exist; a full QuantumTrade-style ladder (RiskEngine → LiveSafetyMonitor → KillSwitch → PortfolioManager) is not assembled as one product surface — and should not be copied wholesale.

**Direction:** Strengthen contracts; allow hosts/plugins to add policy layers without polluting core.

### 3.3 Trading gate + reservation

**Intent:** No LIVE submit without durable authorization and recoverable context.

Implemented direction (see STATUS):

- Durable trading-gate state behind a pluggable state-store boundary
- Versioned pending LIVE execution context with idempotency reservations
- Reconstructible pending context across restart
- LIVE execution depends on a started recovery-backed `ApplicationRuntime` where required
- Submission-time authorization spanning reservation and broker call
- Direct LIVE dispatcher/adapter bypasses blocked

**Rules:**

- Reservation without submit must be recoverable
- Submit without reservation/gate must be impossible on the protected path
- Gate state must survive process restart

### 3.4 Broker submit (adapter boundary)

**Intent:** All external submits cross a single, auditable boundary.

- Host composition constructs credentials/transport and registers identity
- Host must not invent new execution semantics
- Adapter translates domain orders to broker-specific requests and normalizes responses upward

**Current concrete slice:** Dhan production host composition (`DhanHostConfig` / `DhanHostRuntime`) as the implemented pattern to extend.

### 3.5 Receipt capture

**Intent:** Receipts are the system's durable record of what was attempted and what is known.

- Completed broker submissions retain a durable receipt even when idempotency completion is uncertain
- Broker-returned `UNKNOWN` remains durably `PENDING` for reconciliation
- Receipts carry enough identity to support continuation and recovery checks

**Rule:** Do not complete idempotency or advance critical state on UNKNOWN.

### 3.6 Fill / continuation handling

**Intent:** Partial progress is explicit and identity-bound.

- Continuation-chain lineage and aggregate fill validation
- Idempotent continuation dispatch claims
- Reused claims must match authoritative receipt identity, quantity, account, and broker connection

**Rule:** Continuation is reconstruction from evidence, not a best-guess retry policy.

### 3.7 Reconciliation and recovery

**Intent:** After restart, crash, or uncertain broker outcomes, restore safe state without inventing history.

Implemented direction:

- Deterministic pending LIVE recovery with per-context failure isolation
- Malformed persisted contexts isolated with reservation/context identity checks
- Concurrent recovery resolves a pending reservation at most once
- `PendingExecutionRecoveryRunner` remains without broker-submit capability
- Explicit one-shot startup lifecycle: recovery runs before runtime is marked started; failed recovery leaves startup failed

**Rules:**

- Reconstruct from authoritative evidence only
- Prefer leaving work PENDING over optimistic completion
- Recovery must not become a hidden second execution path

### 3.8 Portfolio / position state update

**Intent:** Portfolio and position state move only on accepted evidence.

- Event-driven updates preferred
- No advancement on uncertain submissions
- Keep managers consistent with receipt/continuation outcomes

**Current state:** Domain foundations exist; full QuantumTrade-style event reaction surface may still be thinner — extend only as needed for consistency.

---

## 4. Research and paper path alignment

Backtest and paper paths should reuse the same domain meaning where practical.

### Fill-model honesty

- Record selecting model identity on receipts where applicable (e.g. QUOTE vs BASIC_BAR families)
- Surface limitations in fidelity reporting
- Prefer `BLOCKED` dispositions when data cannot support a safe fill assumption
- Do not synthesize bid/ask merely to force quote semantics onto candle data

### Determinism

- Research replay should be deterministic given the same inputs and model configuration
- Provenance and point-in-time assumptions should be explicit

---

## 5. Startup and runtime composition

### ApplicationRuntime

- Requires a recovery hook
- Runs recovery synchronously before marking started
- Rejects repeated starts
- Leaves startup failed if recovery infrastructure raises

### ProductionRuntime

- Owns durable SQLite lifecycle
- Accepts explicit registry configuration
- Delegates to recovery-backed ApplicationRuntime
- Closes persistence on composition failure
- Does not construct credentials, broker transports, or deployment-specific services itself

This is **validated production composition**, not a claim of full end-to-end production-broker trading.

---

## 6. Mapping to QuantumTrade safety ladder

QuantumTrade packaged a visible ladder:

`RiskEngine → LiveSafetyMonitor → KillSwitch → PortfolioManager → Balance Reconciler`

QuantX maps the *intent* of that ladder onto a recovery-centric control path:

| QT layer idea | QuantX analogue |
|---------------|-----------------|
| RiskEngine | Domain validation + pre-trade risk/policy contracts |
| LiveSafetyMonitor / rate / loss limits | Policy checks + trading gate (extend carefully) |
| KillSwitch | Fail-closed gates, blocked paths, startup refusal on recovery failure |
| Portfolio constraint | Portfolio/position domain rules |
| Balance reconciler | Receipt-based reconciliation + pending recovery |

QuantX should not blindly re-implement QT's product ladder. It should keep the **ordered, fail-closed control idea** and implement it with QuantX's receipt/recovery model.

---

## 7. Non-goals

This document does **not**:

- Define a full strategy product workflow
- Define notification channels
- Define a multi-broker UI
- Claim production-broker end-to-end execution beyond what STATUS validates
- Require a QuantumTrade-identical class hierarchy

---

## 8. Evolution rules

When changing execution behavior:

1. State which layer of the path is affected
2. State whether the change is fail-closed or fail-open
3. State what evidence is required after the change
4. Update STATUS with validation evidence and explicit non-claims
5. If the change is audience-specific or product-shaped, prefer a plugin/host extension over core growth

---

## 9. Related documents

- `docs/STATUS.md` — implemented recovery and LIVE-control evidence
- `docs/architecture/48-quantumtrade-v1.6-migration-map.md` — what was taken from QuantumTrade
- `VISION.md` — core vs plugin boundary
- Production host integration boundary docs under `docs/architecture/`
