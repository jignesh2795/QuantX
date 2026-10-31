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
QuantX normalizes the representation and the range: producers must express their
own judgement as a finite `numbers.Real` value in the inclusive interval
`[0.0, 1.0]`, and the accepted value is stored canonically as a Python `float`.

The field is **not calibrated**. No calibration dataset, reliability measurement,
or hit-rate evidence is attached to it, and the core does not transform it into
a probability. `0.0` and `1.0` are the endpoints of the producer's scale, not
"impossible" and "certain". A probability-like reading requires
producer-specific calibration evidence outside this contract.

### Current producers and consumers

| Path | Relationship to `confidence` |
|---|---|
| `src/quantx/domain/strategy.py` | Defines the field, enforces the `numbers.Real` type and inclusive range, and stores a canonical `float`. |
| `src/quantx/strategy/reference.py` | Only production producer at this revision; emits `1.0` for every BUY, CLOSE, and HOLD signal. `1.0` denotes a fully rule-selected action, not a probability of profit. |
| `StrategyRegistry`, `StrategyRuntime`, `StrategyEvaluationService` | Do not read it. Registry resolves by id/version; runtime and evaluation validate identity, intent, timers, and event time only. |
| `StrategyDeploymentRuntime`, `StrategyExecutionPreparer` | Do not read it. Deployment validation and risk/policy preparation are independent of the score. |
| Backtest and strategy-rehearsal results | Carry the immutable signal through; no filtering, ranking, selection, or promotion path reads the score. |
| Risk, policy, execution, persistence | No production consumer. |

Custom strategies may produce other values in range, but they own the meaning
of their scale. The runtime normalizes only the stored representation; it does
not calibrate or reinterpret the score.

### Comparison semantics and comparability

The numeric value is ordered as an IEEE-754 float, but the core assigns no
ordinal meaning beyond the range. A producer may document that a higher value
means stronger conviction; otherwise consumers must treat the score as opaque.

Two scores are comparable only when all of the following identities match:

- the same `strategy_id` and `strategy_version`;
- the same producer implementation artifact and its recorded version;
- the same producer configuration and scoring-scale definition;
- the same instrument scope.

Values are **instrument-scoped**. `confidence` describes the producer's
judgement for the signal's `instrument` at that event; equal values on two
instruments are not evidence of equal conviction, opportunity, or priority.
Cross-instrument comparison or ranking is undefined.

`StrategySignal` alone cannot establish comparability. It carries
`strategy_id`, `strategy_version`, `instrument`, `action`, `confidence`,
`generated_at`, `reason`, and `signal_id`; it does not carry the producer
implementation, configuration, scoring scale, `StrategyContext`, or run state.
Consumers must obtain those identities from the producer/deployment context and
must treat unknown comparability as not comparable. No additional metadata field
is added to `StrategySignal`: the existing domain contract does not require the
signal to self-certify comparability, and producer/deployment context remains
the authority.

No tolerance, rounding, aggregation, or normalization procedure is defined.
Consumers must not turn the endpoint scale into percentages or expected
returns.

`HOLD` can carry any valid score, including `1.0`; the score does not make a
non-executable action executable or imply that an intent must exist.

### Stability expectations

An immutable signal's value never changes after construction; validation may
normalize the accepted input to `float` once. A deterministic strategy must
produce the same score for the same complete inputs:

- `StrategyContext.event` and `StrategyContext.as_of`;
- `StrategyContext.ir` and the typed `StrategyContext.params` derived from it;
- `StrategyContext.engine` (`EngineStateSnapshot`, including position and order
  evidence availability);
- `StrategyContext.history` (the immutable candle tuple);
- the producer implementation and its recorded version;
- the producer configuration and scoring-scale definition;
- the signal instrument;
- run-scoped mutable strategy state.

`StrategyContext` is the full runtime input surface and carries no broker or
execution capability. Strategies may nevertheless keep mutable state for the
duration of a run. For example, the reference `BuyThenCloseStrategy` records
entered and closed instruments in instance sets. That state is not represented
in `StrategyContext` or `StrategySignal`, can change between events, and must be
initialized deterministically at the start of each run. Two runs that differ in
accumulated strategy state are not identical even when the current event and
parameters match.

Any change to the producer implementation, configuration, scale, or meaning
requires a new `strategy_version` (and an updated recorded implementation
version); scores from different versions are not comparable. Model-backed or
externally supplied strategies may be nondeterministic, and their score must not
be treated as repeatable evidence unless the producer provides that guarantee
separately.

### Selection boundary

Strategy selection and signal selection are different decisions and must not be
conflated:

- **Strategy selection** chooses which strategy, version, or deployment is
  registered, resolved, run, or promoted.
- **Signal selection** chooses whether a produced signal is retained, ranked,
  filtered, or acted upon.

At this revision no registry, runtime, evaluation, deployment, backtest,
rehearsal, filtering, risk, or execution path selects, ranks, or filters on
`confidence`. The registry resolves an exact strategy id/version; it does not
rank strategies. There is no implicit signal filter: every validated signal is
carried through unchanged, and a `HOLD` or otherwise non-executable result stays
non-executable regardless of its score.

Confidence-based **strategy selection is explicitly prohibited** under the
current contract. No consumer may choose, rank, promote, or demote a strategy or
strategy version using `confidence`, including within one strategy id/version.

Confidence-based signal selection or filtering is also not authorized now. It
requires a separately specified, named, versioned, and tested policy contract
that is approved on its own evidence before any consumer may use the score.
Until that contract exists, no confidence-based selection or filtering is
permitted.

Any future policy must define at least:

- **candidate population** — exactly which signals or strategies are eligible,
  why they are comparable under the identity rules above, and how ineligible
  entries are excluded;
- **instrument scope** — whether candidates are restricted to one instrument, a
  named set, or cross-instrument comparison, with the justification for that
  scope;
- the producer implementation, configuration, scoring-scale, and version
  assumptions;
- ordering, ties, missing or invalid scores, and fail-closed behavior;
- that it runs after runtime validation and before risk/policy preparation and
  never creates an intent, upgrades `HOLD`, sizes an order, or bypasses the
  canonical risk/policy/execution path.

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

Construction accepts any finite `numbers.Real` value in `[0.0, 1.0]` except
`bool`, and stores the accepted value canonically as a Python `float`:

| Input | Result |
|---|---|
| `int` such as `0`, `1` | Accepted; normalized to `0.0`, `1.0` (`float`) |
| `float` such as `0.5` | Accepted; stored as `float` |
| `Fraction` such as `Fraction(1, 2)` | Accepted; normalized to `0.5` (`float`) |
| `bool` (`True`, `False`) | Rejected with `TypeError`; booleans are not scores |
| `Decimal` such as `Decimal("0.5")` | Unsupported; rejected with `TypeError` naming `Decimal` |
| other non-`numbers.Real` values | Rejected with `TypeError` naming the actual type |
| NaN, infinities, and values outside `[0.0, 1.0]` | Rejected with `ValueError` |

Range validation uses the accepted real value before normalization, so a
`Fraction` outside the range is rejected with the same `ValueError` instead of
an overflow error during conversion. Error messages distinguish a rejected
`bool`, an unsupported type (naming the actual type and the `numbers.Real`
requirement), and an out-of-range value.

#### Validation change record

| Revision | Accepted input | Stored value | Rejected |
|---|---|---|---|
| Initial contract | `int`, `float` | Input value unchanged; an `int` remained an `int` despite the `float` annotation | `bool`, non-numeric values, `Decimal`, NaN, infinities |
| Current remediation | Any finite `numbers.Real` except `bool` | Canonical Python `float` | `bool`, `Decimal`, other non-`numbers.Real` values, NaN, infinities, out-of-range values |

This table is the authoritative record of the validation change. Any future
change to accepted types, normalization, or error semantics must add a row here
and update the tests in `tests/unit/domain/test_strategy.py`.

## Benefits

- one strategy lifecycle
- backtest/paper/live parity
- reusable visual and code strategies
- AI can generate normal strategy definitions rather than privileged broker code
- external integrations can submit normalized intent without bypassing risk
