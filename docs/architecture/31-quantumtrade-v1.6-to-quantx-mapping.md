# QuantumTrade v1.6 → QuantX Mapping

## Purpose

QuantumTrade v1.6 is the engineering baseline and source of proven ideas. It is not copied wholesale into QuantX.

## Keep / generalize

| QuantumTrade area | QuantX treatment |
|---|---|
| Immutable domain contracts | Keep and generalize |
| Event bus/events | Keep and generalize |
| Clock abstraction | Keep |
| Order lifecycle | Keep and generalize |
| Order manager | Keep and generalize |
| Risk engine | Keep and extend for Indian F&O |
| Kill switch / safety | Keep and strengthen |
| Live safety monitor | Keep and generalize |
| Wallet | Keep concept; generalize to currencies/accounts |
| Position model | Keep concept; redesign for contracts and multi-leg positions |
| Portfolio manager | Keep and extend |
| Capital manager | Keep and generalize |
| Balance reconciliation | Keep and make a formal recovery boundary |
| BotSession | Keep as an application-service concept |
| REST layer | Keep concept; stabilize as public API |
| WebSocket layer | Keep concept; formalize event/data contracts |
| EventBus → WebSocket bridge | Keep |
| Paper execution | Keep as first-class execution environment |
| Backtesting | Keep concepts; consolidate duplicate engines |
| Walk-forward | Keep in research layer |
| Monte Carlo | Keep in research layer |
| Robustness/reality checks | Keep in research layer |
| Binance adapter | Keep only as a plugin/adapter |
| CLI | Keep as a developer/admin application |

## Generalize before reuse

The following QuantumTrade assumptions must not enter the QuantX kernel:

```text
USDT as universal money
Binance as universal venue
BTC/USDT as a canonical instrument
crypto minimum-notional rules
Binance fee assumptions
crypto-only market sessions
spot-only position assumptions
```

## Redesign for QuantX

```text
Instrument / Contract model
Futures and options
Multi-leg positions
Margin
Indian charges
Market calendar
Corporate actions
Broker capabilities
Strategy lifecycle
Plugin permissions
State ownership
Recovery/reconciliation
Execution models
Data provenance
```

## V1.6 API work

The v1.6 REST/WebSocket/session work should be treated as the first evidence of a service boundary, not as the final QuantX API design.

Target layering:

```text
REST/WebSocket/CLI
        ↓
Application services
        ↓
Domain contracts
        ↓
Ports
        ↓
Adapters
```

## Test inheritance

QuantumTrade's testing discipline is a major asset. QuantX should retain the idea of testing architecture and contracts, while adding:

- broker contract tests
- replay determinism tests
- recovery/reconciliation tests
- idempotency tests
- plugin compatibility tests
- architecture import-boundary tests
- execution realism scenario tests

## Decision

QuantumTrade v1.6 remains a reference implementation and engineering laboratory. QuantX is the generalized open-source platform. Reuse is evaluated by boundary and contract, not by copying the repository tree.
