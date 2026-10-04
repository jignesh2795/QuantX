# QuantX Engineering Practices

Practical rules for keeping QuantX correct, focused, and extensible.

These complement:

- `docs/STATUS.md` — evidence of what is validated
- `docs/roadmap/PHASES.md` — tight near-term phases
- `docs/architecture/control-and-safety-path.md` — ordered control path
- `VISION.md` — core vs plugin boundary

---

## 1. Evidence-first STATUS discipline

STATUS is the source of truth for implementation reality.

**Rules:**

- Every non-trivial execution/recovery change updates STATUS with what passed and what is still not claimed
- Never imply production-broker end-to-end trading unless it was actually run and recorded
- Prefer commit hashes, test counts, and explicit non-claims over narrative confidence
- Roadmap and PHASES sequence work; they do not override STATUS

---

## 2. Phase sign-off template

When closing a tight phase from `PHASES.md`, append a short STATUS entry:

```text
Phase Px closed: <name>
Validated:
- <bullet>
- <bullet>
Non-claims:
- <bullet>
- <bullet>
Evidence: <tests / commit / notes>
Next: Py — <name>
```

**Rules:**

- Do not close a phase on partial work; split the phase instead
- Exit criteria in PHASES.md are the checklist for closure
- Active phase should be obvious from the STATUS header

Suggested STATUS header line while a phase is open:

```text
Current phase: Px — <name> (see docs/roadmap/PHASES.md)
```

---

## 3. Fail-closed checklist (execution PRs)

Before merging work that touches LIVE submit, recovery, gates, receipts, or continuation, answer all of the following:

1. **UNKNOWN:** What happens if the broker returns UNKNOWN?
2. **Crash:** What happens if the process crashes mid-submit?
3. **Recovery submit:** Can recovery code submit to the broker? (must be **no**)
4. **Bypass:** Does any path bypass the trading gate or approved dispatcher?
5. **Evidence:** Is critical state advanced only on authoritative evidence?
6. **Startup:** If startup recovery fails, is the runtime left unstarted/failed?
7. **Tests:** Are the above paths covered by focused tests?

If any answer is fuzzy, the change is not ready.

---

## 4. ADR-lite for irreversible decisions

When choosing something hard to reverse, write a short decision record under `docs/decisions/`:

```text
# ADR-XXXX: <title>

## Context
<why this came up>

## Decision
<what we chose>

## Consequences
<what becomes easier / harder>

## Alternatives rejected
<what we did not choose and why>
```

Use for:

- Receipt and idempotency semantics
- Trading-gate / reservation rules
- Recovery startup lifecycle
- Fill-model policy (e.g. no synthetic bid/ask for candles)
- Core vs adapter responsibility splits

Do **not** write an ADR for routine bugfixes or pure refactors.

---

## 5. Scope freeze per open phase

While a phase is open:

- No drive-by broker expansion
- No UI / CLI product work
- No strategy framework expansion
- No optimizer / notification / AI surface work
- Only changes that unblock that phase's exit criteria (plus critical fixes)

If new work is important, either:

- finish the current phase first, or
- split a new tight phase and sequence it explicitly

---

## 6. Port and adapter contract tests

At broker/data port boundaries:

- Test normalization into domain types
- Test capability rejection (unsupported order type, segment, operation)
- Test that core logic does not require a specific broker SDK
- Prefer contract tests at the port, not end-to-end live calls, for default CI/local gates

**Rule:** Broker quirks stay in adapters. Core stays venue-capable, not venue-entangled.

---

## 7. Determinism budget (research / paper)

For research and paper execution changes:

- Same inputs + model config → same outputs
- Selecting fill-model identity recorded where applicable
- Limitations and assumptions explicit in fidelity/reporting
- Prefer `BLOCKED` (or equivalent) over invented microstructure
- Do not synthesize bid/ask solely to force quote semantics onto candle data

This is part of P9/P10 exit thinking in PHASES.md.

---

## 8. Boundary and dependency hygiene

- Core must not import broker SDKs
- Hosts and adapters may import broker SDKs
- Research tools must not redefine execution semantics
- Plugins consume stable contracts; they do not casually reshape domain types
- Production host composition wires identity and lifecycle; it does not invent new execution meaning

Document first. Automate import/boundary checks later if violations become common.

---

## 9. Named validation environments

Always name the environment you validated:

| Name | Meaning |
|------|--------|
| Unit / contract | Default local tests |
| Local recovery simulation | Restart/pending/UNKNOWN scenarios without real broker submits |
| Paper | Simulated execution path |
| Live | Real broker path — only claim when actually exercised |

Never blur local recovery success with “live trading validated.”

---

## 10. Public non-goals (protect the core)

Until explicitly reopened by phase/milestone decisions, treat as non-goals for core:

- Multi-broker UI product
- Optimizer / walk-forward product surface
- AI trading agents
- Notification products (e.g. Telegram) as built-ins
- Guaranteed-profit or signal-marketplace positioning

Audience-specific or product-shaped work belongs in plugins or separate projects per VISION.md.

---

## 11. Implementation loop (default)

For each change:

1. Inspect existing code and docs
2. Identify one concrete integrity or contract gap
3. Make the smallest non-duplicative production change
4. Add a focused regression test
5. Run focused validation, then broader suite as appropriate
6. Run lint/type checks where applicable
7. Update STATUS if claims or non-claims changed
8. Leave no unrelated churn

---

## 12. What not to prioritize early

- Heavy process overhead (large boards, ceremony)
- Broad contributor policy before you want external contributors
- Full CI matrix while tooling/billing constraints block it
- Product telemetry / SaaS operations practices

Correctness and clear boundaries first.

---

## Related documents

- `docs/STATUS.md`
- `docs/roadmap/PHASES.md`
- `docs/architecture/control-and-safety-path.md`
- `docs/planning/quantumtrade-transfer-map.md`
- `docs/implementation/README.md`
- `VISION.md`
