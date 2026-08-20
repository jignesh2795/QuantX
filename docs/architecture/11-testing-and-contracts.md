# QuantX Testing and Contract Validation

Testing is part of the architecture, not a final phase.

## Core tests

- domain invariants
- order lifecycle
- fill and position accounting
- risk decisions
- portfolio accounting
- deterministic replay

## Contract tests

Every broker and data adapter must pass common interface tests.

## Simulation tests

Test realistic behavior including:

- slippage
- latency
- partial fills
- rejection
- disconnects
- duplicate events
- stale market data
- out-of-order events
- broker reconciliation

## Plugin compatibility

Each plugin declares its supported QuantX API range and capabilities. CI should validate the plugin against the relevant contract suite.

## Integration gates

Before merge, the project should eventually run:

```text
lint
↓
type checks
↓
unit tests
↓
contract tests
↓
integration tests
↓
backtest smoke test
↓
API/WS smoke tests
```
