# Capital Source and Broker Constraints

## Principle

QuantX must never assume a minimum starting balance or impose a hidden minimum capital requirement.

Capital availability is an observed or explicitly configured runtime input.

## Capital sources

- `LIVE_BROKER`: current balance/equity/margin fetched from the connected broker account.
- `PAPER_CONFIGURED`: starting balance explicitly configured by the user for the paper account.
- `BACKTEST_CONFIGURED`: starting capital explicitly supplied for a backtest or experiment.

## Broker/exchange constraints

A broker, venue, instrument, or exchange may explicitly impose constraints such as:

- minimum order quantity
- minimum notional/order value
- lot size
- margin requirement
- required collateral
- product-specific capital requirements
- price/tick constraints
- account eligibility restrictions

These are valid constraints because they originate from the execution venue or its configured rule set. They must be represented as explicit capabilities/rules and must not be converted into a universal QuantX minimum-capital assumption.

## Evaluation model

```text
Available Account Capital
          +
Broker/Venue Constraints
          +
Instrument/Contract Rules
          +
Risk Policies
          ↓
Executable or Rejected
```

For example, an account with available capital of ₹7,350 is not rejected merely because QuantX has no assumed threshold. It may be rejected only when the requested trade cannot satisfy the actual broker, instrument, margin, or configured risk constraints.

## Strategy rule

Strategies must request sizing/capital information through domain services. They must not hard-code account minimums such as `$20`, `$1000`, or any project-specific starting balance.

## Paper mode

Paper mode uses exactly the configured paper balance. If no paper balance is configured, paper execution must fail with a configuration error rather than silently choosing a default starting capital.

## Backtest mode

Backtests require an explicit starting capital as part of experiment configuration. This makes results reproducible and prevents hidden defaults from changing performance outcomes.

## Design consequence

Broker-specific minimums belong in broker/instrument capability and policy layers. Universal capital assumptions do not belong in the domain kernel.
