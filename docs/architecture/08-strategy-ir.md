# QuantX Strategy Intermediate Representation

QuantX should expose one strategy model to multiple authoring surfaces.

## Authoring sources

- Python strategies
- Visual Flow definitions
- AI-generated strategies
- External signals and webhooks

## Common path

```text
Python / Flow / AI / External Signal
                ↓
       Strategy Definition / IR
                ↓
       Validation + Capability Check
                ↓
             Runtime
                ↓
           TradeIntent
```

The IR is not a broker API. It describes strategy intent and workflow semantics. Risk, policy and execution remain controlled by QuantX services.

## StrategySignal confidence contract

`StrategySignal.confidence` is a **bounded, producer-declared conviction score**.
QuantX normalizes only the range: producers must express their own judgement as
a finite number in the inclusive interval `[0.0, 1.0]`.

The field is **not calibrated**. No calibration dataset, reliability measurement,
or hit-rate evidence is attached to it, and the core does not transform it into
a probability. `0.0` and `1.0` are the endpoints of the producer's scale, not
"impossible" and "certain". A probability-like reading requires
producer-specific calibration evidence outside this contract.

### Current producers and consumers

| Path | Relationship to `confidence` |
|---|---|
| `src/quantx/domain/strategy.py` | Defines the field and enforces type and range. |
| `src/quantx/strategy/reference.py` | Only production producer at this revision; emits `1.0` for every BUY, CLOSE, and HOLD signal. `1.0` denotes a fully rule-selected action, not a probability of profit. |
| `StrategyRegistry`, `StrategyRuntime`, `StrategyEvaluationService` | Do not read it. Registry resolves by id/version; runtime and evaluation validate identity, intent, timers, and event time only. |
| `StrategyDeploymentRuntime`, `StrategyExecutionPreparer` | Do not read it. Deployment validation and risk/policy preparation are independent of the score. |
| Backtest and strategy-rehearsal results | Carry the immutable signal through; no filtering, ranking, selection, or promotion path reads the score. |
| Risk, policy, execution, persistence | No production consumer. |

Custom strategies may produce other values in range, but they own the meaning
of their scale. The runtime neither computes nor rewrites it.

### Comparison semantics

- Values are ordered IEEE-754 numbers, but the core assigns no ordinal meaning
  beyond the range. A producer may document that a higher value means stronger
  conviction; otherwise consumers must treat the score as opaque.
- Values are comparable only within the same `strategy_id` and
  `strategy_version` (and the same producer-defined configuration). `0.5` from
  one strategy or version has no defined relation to `0.5` from another.
- No tolerance, rounding, aggregation, or normalization procedure is defined.
  Consumers must not turn the endpoint scale into percentages or expected
  returns.
- `HOLD` can carry any valid score, including `1.0`; the score does not make a
  non-executable action executable or imply that an intent must exist.

### Stability expectations

An immutable signal's value never changes after construction. A deterministic
strategy must produce the same score for the same event, parameters, engine
evidence, and strategy version. Any change to the producer's scale or meaning
requires a new `strategy_version`; scores from different versions are not
comparable. Model-backed or externally supplied strategies may be
nondeterministic, and their score must not be treated as repeatable evidence
unless the producer provides that guarantee separately.

### Selection boundary

At this revision no registry, runtime, evaluation, deployment, backtest,
rehearsal, filtering, risk, or execution path selects on `confidence`. The
registry resolves an exact strategy id/version; it does not rank strategies.

A future, explicitly composed strategy-selection policy **may** use the score
as a documented ranking hint only when all of the following hold:

- it ranks candidates from the same strategy id and version that the producer
  has given an ordinal scale for;
- it is named, separately configured, and tested as a selection policy;
- it runs after runtime validation and before risk/policy preparation;
- it never creates an intent, upgrades `HOLD`, or bypasses the canonical
  risk/policy/execution path.

Cross-strategy comparison or optimization on this field is not permitted
without calibration evidence and a separate contract.

### Separation from money, risk, and execution authorization

`confidence` is not a price, quantity, fee, balance, P&L, valuation, margin,
exposure, drawdown, risk limit, broker observation, or execution authorization.
It must not be used to size an order, approve or reject risk, trip or reset the
trading gate, choose a broker/account/execution mode, or authorize submission.
Any risk or execution policy that wants to use a confidence-like input needs a
separate named, validated policy with its own evidence and failure semantics;
this field cannot be that policy.

### Type and validation

The field is intentionally `float`, not `Decimal`. It is a model/strategy
score, not exact financial arithmetic; converting it to `Decimal` would imply a
precision and accounting semantics that no producer provides. No domain or API
requirement for exact decimal confidence arithmetic has been identified.

Construction accepts finite `int`/`float` values in `[0.0, 1.0]` and rejects
`bool`, non-numeric values, `Decimal`, NaN, and infinities. Callers should pass
a `float`; the inclusive endpoints are valid.

## Benefits

- one strategy lifecycle
- backtest/paper/live parity
- reusable visual and code strategies
- AI can generate normal strategy definitions rather than privileged broker code
- external integrations can submit normalized intent without bypassing risk
