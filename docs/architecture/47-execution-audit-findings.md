# Execution Audit Findings

## Current decisions

The execution package is intentionally not split into folders merely for visual symmetry. A module remains standalone when it has one cohesive responsibility.

### Canonical modules

- `ports.py`: execution port for already-approved requests.
- `market_ports.py`: execution port that explicitly requires a point-in-time `MarketSnapshot`.
- `market_data.py`: observable market snapshot contract.
- `models.py`: deterministic fill/slippage model contracts.
- `paper.py`: paper/shadow/replay execution engine.
- `paper_session.py`: end-to-end paper orchestration across execution, accounting and valuation.
- `accounting.py`: fill-to-position accounting.
- `valuation.py`: position mark-to-market valuation.
- `portfolio_valuation.py`: portfolio-level valuation orchestration.
- `order_lifecycle.py`: order state machine.
- `idempotency/`, `preconditions/`, `receipts/`, `transactions/`: dedicated execution safety/orchestration boundaries.

## `ports.py` vs `market_ports.py`

These are intentionally different contracts, not duplicates.

`ExecutionPort.execute(request)` represents an execution implementation that owns or obtains its required execution inputs.

`MarketDataExecutionPort.execute(request, snapshot=...)` explicitly requires a caller-supplied point-in-time market snapshot. This is useful for deterministic replay/paper components and prevents hidden market-data access.

Do not merge these merely to reduce file count.

## `paper.py` vs `paper_session.py`

These are also intentionally different responsibilities.

- `PaperExecutionEngine` determines whether and how an approved order fills from supplied market data and execution models.
- `PaperSession` orchestrates execution -> fill accounting -> valuation.

Do not merge them into one large module.

## Important correctness finding

`PaperSimulationProfile` currently declares latency and fee parameters, but the current paper engine records those values in the receipt assumptions without applying latency or fees to the resulting execution/accounting path. This must be corrected before describing the simulator as high-fidelity.

## Important correctness finding: instrument metadata

`paper_session.py` currently contains a compatibility `resolve_instrument()` helper that constructs an `Instrument` with defaults including:

- equity asset class;
- INR/USD currency based on region;
- tick size `0.01`;
- lot size `1`;
- multiplier `1`.

Those are implementation defaults and must not become the universal instrument model. They violate the project's rule that market/broker constraints and instrument metadata must come from explicit registry/venue evidence. This helper should be replaced with an instrument-registry lookup before broad paper/live use.

## Next action

Do not restructure these modules further. Fix the two correctness issues above, then continue the integration audit.
