---
name: quantx-core-governance
description: Mandatory baseline for every QuantX task — non-negotiable safety, evidence, Decimal/fail-closed rules, ownership boundaries, control-path safety review, and core-vs-plugin rules. Load first, before any other quantx skill.
metadata:
  quantx/role: governance
---

# QuantX Core Governance

You are working on QuantX, an open-source modular event-driven algo-trading platform for Indian markets.

## Current technical baseline

- Python 3.12; source under `src/quantx`; tests under `tests/unit/`.
- SQLite persistence; pytest; Ruff (line 100); mypy `--strict`; uv package manager.
- Dhan is the first broker/market-data plugin. `dhanhq` SDK imports belong ONLY in `src/quantx/plugins/dhan/transport.py`.
- Architecture: modular monolith, ports-and-adapters, capability-based plugins, event-driven domain core.
- Canonical execution flow: `Strategy → TradeIntent → Risk → Policy → ApprovedExecutionRequest → Execution → ExecutionReceipt → Fill → Position → Portfolio`.

Before non-trivial work, read: `docs/STATUS.md`, `docs/architecture/README.md`, `docs/implementation/README.md`, and the source/tests being changed.

## Authority precedence

1. Actual repository code and current canonical repository docs.
2. Current task requirements.
3. This skill.
4. Older prompts, stale branch notes, or copied plans.

Never silently reconcile contradictions. Verify against the repository and flag the contradiction.

## Ownership model

The primary AI agent owns: architecture decisions, workstream sequencing, scope selection, branch/commit/PR decisions, implementation, code/doc changes, audits and adversarial review, merge/release decisions.

The owner supplies only requested validation evidence unless explicitly taking back a decision. Do not ask the owner to design the solution when the repository and requirements provide enough evidence to decide.

When a task is explicitly VALIDATION ONLY, do not edit anything.

## Non-negotiable engineering rules

- Core domain/application/execution stays free of broker SDKs, credentials, and web frameworks.
- **Decimal is mandatory** for money, prices, monetary quantities, and financial calculations. Never use float for financial math.
- Reject NaN, infinity, and bool values where numeric contracts require real numbers.
- Deterministic and fail-closed by default.
- **Unknown is not zero. UNKNOWN is never PASS.**
- Never fabricate defaults for missing market/broker evidence.
- Conflicting authoritative data must be surfaced explicitly; never silently overwrite.
- Secrets come only from environment/secret configuration; never hardcode credentials.
- Reuse existing types and boundaries. No catch-all utility/model modules (`utils.py`, `services.py`, `models.py`).
- One canonical implementation per responsibility.
- One focused branch/PR per coherent task.
- Never claim tests, production behavior, or broker behavior that was not actually verified.
- No real broker orders as part of development or validation.

## Control-path safety review

For execution behavior, reason using the control path:

```
intent → domain validation → pre-trade risk/policy → gate + reservation
  → broker submit → receipt → continuation → reconciliation/recovery → position update
```

Any change touching idempotency, LIVE guards, trading gate, reconciliation, UNKNOWN states, recovery, position/loss limits, or timeouts requires an explicit safety review answering:

1. Which control-path layer is touched?
2. Fail-closed or fail-open?
3. What evidence is required after the change?
4. What happens on UNKNOWN?
5. Can recovery submit? (normally must be NO)
6. Can any path bypass the gate/approved dispatcher?
7. Is critical state advanced only on authoritative evidence?
8. What tests prove each answer?

If any answer is fuzzy, stop and investigate rather than guessing.

## Core vs module vs plugin

- **CORE**: safety/contracts/recovery/accounting primitives that must be universal.
- **INDIA**: Indian market semantics and versioned venue/rule data; the universal core defines portable contracts only.
- **PLUGIN**: analytics, optimizers, UI, AI/agents, notification channels, extra brokers, strategy packs, and other optional product surfaces — unless a task explicitly promotes a capability into core.

## Work discipline

Inspect before editing. Reuse before inventing. Make the smallest coherent change. Keep historical evidence intact. Separate cleanup from behavior changes.
