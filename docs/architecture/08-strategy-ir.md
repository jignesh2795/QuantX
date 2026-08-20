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

## Benefits

- one strategy lifecycle
- backtest/paper/live parity
- reusable visual and code strategies
- AI can generate normal strategy definitions rather than privileged broker code
- external integrations can submit normalized intent without bypassing risk
