# Flow v1 compiler and interpreter

## Scope and runtime boundary

F4.5.2 compiles the validated, closed Flow v1 catalogue into an immutable execution plan and evaluates that plan against one existing immutable `StrategyContext`. Compilation validates the full definition before producing instructions. A min-heap topological traversal gives a stable node-ID tie-break when multiple nodes are ready. The plan fingerprint binds the canonical definition, compiler contract and Decimal contract versions to the ordered instruction/binding sequence.

The interpreter revalidates a supplied plan by recompiling its retained definition and comparing the complete immutable value. Constructing or editing a plan object is therefore not a way to bypass graph validation.

Evaluation returns the existing `StrategyResult` containing `StrategySignal` and optional passive `TradeIntent` values. It does not implement `ExecutableStrategy`, register a strategy, reserve/submit an order, or invoke risk, policy, paper, backtest, broker or LIVE behavior. Those remain separate F4.5.3/F4.5.4 integration gates through the established runtime.

## Decimal contract

`FLOW_DECIMAL_CONTRACT_VERSION = "1"` defines arithmetic semantics for this interpreter:

| Setting | Contract |
|---|---|
| Precision | 34 significant digits |
| Rounding | `ROUND_HALF_EVEN` |
| Minimum exponent | -6143 |
| Maximum exponent | 6144 |
| Trapped conditions | Clamped, InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation |
| Permitted conditions | Inexact, Rounded and exact Subnormal results, governed by the pinned precision and rounding |

Every arithmetic node and quote midpoint uses a fresh local Decimal context with these settings. It does not inherit ambient thread precision, rounding or traps. Division by zero has its own stable diagnostic; other trapped arithmetic conditions map to a stable arithmetic error. Non-finite inputs and results are rejected. Decimal values remain Decimal throughout the graph. Conversion to float occurs only when the bounded confidence value is passed to the existing `StrategySignal` domain constructor.

## Context and evidence semantics

- Event fields read only the current event and the matching canonical payload type. A Quote/Candle payload whose `MarketDataType` or timestamp does not agree with its event fails closed.
- `bars_ago=1` means the last candle in strictly chronological, unique, same-instrument history. History must be strictly earlier than both event time and context `as_of`, and is capped at 512 candles. The interpreter never sorts or fabricates history.
- A complete empty position collection means quantity zero for the current instrument. Incomplete/unavailable position evidence remains unavailable; duplicate complete facts for that instrument are rejected.
- A witnessed nonterminal order (including `UNKNOWN`) proves that an active order exists even in an incomplete collection. No matching active order proves false only when the collection is complete. Incomplete/unavailable absence remains unknown.
- No position/order fact for another instrument is supplied to a Flow node.

## Determinism

Signal and intent identifiers are UUIDv5 values derived from a canonical invocation identity containing the plan fingerprint, Decimal contract version, current event, context information cut, bounded history and same-instrument engine evidence. The generated signal timestamp is the current event timestamp. The interpreter reads no wall clock and uses no random UUID generation.

Missing values remain `None` until explicitly handled by `is_available_*`, `require_*` or `select_*` nodes. This compiler/interpreter is a deterministic expression layer, not a strategy lifecycle, execution engine or authorization boundary.
