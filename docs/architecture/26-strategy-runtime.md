# Strategy Runtime and Strategy IR

Status: Draft

## Principle

Python strategies, visual flows, external signals and future AI-generated strategies must converge on common QuantX trading semantics.

They must not create separate execution engines.

## Strategy inputs

```text
Python Strategy
Visual Flow
Webhook / External Signal
AI-generated Strategy
Scheduled Rule
```

## Common runtime

```text
Strategy Input
  -> Strategy Definition / Controller
  -> TradeIntent
  -> Policy Engine
  -> Risk Engine
  -> Order
```

## Strategy IR

QuantX should define a versioned intermediate representation for declarative strategy definitions. It should be expressive enough for visual flows and AI generation while remaining compatible with imperative Python strategies.

A conceptual IR contains:

- metadata
- instruments/contract selectors
- data requirements
- indicators/features
- conditions
- actions
- risk requirements
- position rules
- lifecycle rules
- required capabilities
- scheduling/session constraints

The IR is a planning representation, not a broker order language.

## Controllers and executors

Complex strategies may be composed from controllers and executors:

```text
Strategy Controller
  -> Entry Executor
  -> Exit Executor
  -> Hedge Executor
  -> Rebalance Executor
  -> Expiry/roll Executor
```

Executors create intents and orders through the normal application services. They do not bypass risk.

## Strategy contexts

The same strategy contract should work in:

- historical backtest
- deterministic replay
- sandbox
- paper
- live

Only environment ports change.

## AI boundary

AI may generate, inspect, explain or optimize a strategy definition. AI must not receive a direct broker-order bypass. Any live action must enter the canonical TradeIntent -> Policy -> Risk -> Order path.
