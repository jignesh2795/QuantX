---
name: quantx-simulation-accounting
description: QuantX paper/backtest accounting knowledge — fill accounting, cash and margin ledgers, valuation, account financial state, P&L, charges, partial fills, and simulation honesty. Use when working on backtest or paper money accounting, valuation, or charges — distinct from order submission and reconciliation (quantx-execution).
metadata:
  quantx/role: simulation-accounting
---

# QuantX Simulation & Accounting

Accounting/valuation knowledge layer. For order submission, receipts, reconciliation, and recovery, see `quantx-execution`.

## One accounting path

Canonical flow:

```
execution/fills → FillAccounting → CashLedger → account state → P&L
```

Do not create parallel accounting or P&L implementations.

| Concern | Module |
|---|---|
| Fill/accounting primitives | `src/quantx/execution/accounting.py` |
| Cash ledger | `src/quantx/execution/cash_ledger.py` |
| Margin ledger | `src/quantx/execution/margin_ledger.py` |
| Margin policy | `src/quantx/execution/margin_policy.py` |
| Valuation | `src/quantx/execution/valuation.py` |
| Portfolio valuation | `src/quantx/execution/portfolio_valuation.py` |
| Account financial state | `src/quantx/execution/account_financial_state.py` |
| Account state (domain) | `src/quantx/domain/finance.py` (`AccountFinancialState`, `CapitalSourceType`) |
| Portfolio primitives | `src/quantx/domain/portfolio.py` |
| Full session orchestration | `src/quantx/execution/paper_session.py` |
| Backtest composition | `src/quantx/application/backtest.py` (`DeterministicBacktestService`) |

## Simulation honesty

A simulated fill is evidence of a model/configuration, not broker truth. Preserve model ID/version/provenance and explicit assumptions (`execution/models.py` — `FillModel`, `QuoteFillModel`, `SlippageModel`; `execution/paper/profile.py`).

Paper venue invariants: missing required quotes never create invented fills; repeated client order IDs are idempotent; the matcher never invents market data.

## Valuation

- No fabricated marks — missing valuation evidence remains incomplete.
- Decimal-only financial math; decimals persisted via `str()`, never binary float.
- Signed market value where positions require it.
- Gross exposure stays distinct from signed/net exposure.
- Timestamped marks must expose `observed_at` vs `selected_at` when an as-of mark is reused.

## Partial fills

Never exceed requested quantity. Remainders must be explicit and integrated with the existing continuation/lifecycle semantics (`execution/continuation.py`, `execution/order_lifecycle.py`).

## Charges

Keep execution price realization separate from transaction-cost calculation. Preserve the existing aggregate receipt fee/accounting path while allowing structured charge evidence.

## Backtests

- Do not assume static account state if the task requires evolving cash/positions.
- Keep derived research series out of pre-trade risk unless explicitly designed as a safety contract.
- Backtest, sandbox, paper, and live share the same trading semantics — accounting must not diverge by mode.

## Testing

```powershell
uv run pytest tests/unit/execution -q
uv run pytest tests/unit/application/test_backtest.py -q
```
