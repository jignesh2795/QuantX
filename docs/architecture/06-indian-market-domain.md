# QuantX Indian Market Domain

QuantX is Indian-market first while keeping the universal core market-neutral.

## Initial instruments

- equity
- ETF
- index
- futures
- options

## First-class contract attributes

- venue and exchange
- symbol / instrument identifier
- currency
- tick size
- lot size
- multiplier
- expiry
- strike
- option type
- trading session
- product type

## F&O requirements

The domain must support multi-leg positions and execution, including option selection, expiry handling, margin, Greeks, slippage, partial fills, leg sequencing, hedging and re-entry.

## Market rules

Broker and exchange rules such as trading sessions, quantity constraints, price bands, fees, charges and margin requirements belong behind venue/domain policy boundaries rather than being hard-coded in strategies.

## Generalization

Crypto and international markets can be added later as adapters/extensions without changing the universal order, risk, execution and event semantics.
