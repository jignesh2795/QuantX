# R1-C5 Transaction-Cost and Charges Fidelity

## Purpose
R1-C5 makes transaction costs a first-class, deterministic contract for paper and research execution.

The contract separates:
- charge calculation;
- charge component breakdown;
- model version and provenance;
- the aggregate receipt fee used by existing cash/accounting paths.

The slice deliberately does not embed current broker tariffs, Indian statutory rates, or exchange-specific schedules in the universal core.

## Charge contract

src/quantx/execution/charges.py defines:

- ChargeCalculationContext: explicit transaction value and optional settlement currency;
- ChargeComponent: one non-negative, Decimal-valued named component;
- ChargeBreakdown: immutable components plus model identity/version/provenance;
- ChargeModel: deterministic calculation port;
- PercentageBpsChargeModel: generic configured percentage model.

ChargeBreakdown.total is the authoritative aggregate of its components.

Component names must be unique. Non-Decimal monetary inputs are rejected.

## Receipt boundary

ExecutionReceipt keeps the existing fee field for compatibility.

When charges is present:

  receipt.fee == receipt.charges.total

A mismatch is rejected. Paper execution records the configured model identity, version, provenance, and computed total in the receipt assumptions as well as the structured breakdown.

A receipt without a structured breakdown remains valid for compatibility with existing integrations and broker observations that only supply an aggregate charge.

## Current paper model

The existing fee_bps configuration is now represented by PercentageBpsChargeModel when no explicit charge model is supplied.

Its basis is deliberately explicit:

  transaction_value = fill.quantity * fill.price
  charge = transaction_value * rate_bps / 10000

This is a generic quote-notional simulation model, not a statement about any broker's live tariff.

Future models can use a richer explicitly supplied transaction-value basis without changing the receipt or accounting contract.

## Caller-supplied per-fill cost schedules

The canonical ChargeModel boundary also supports an immutable, explicitly supplied
CostScheduleChargeModel. This is a generic paper/research model; it does not provide
broker or statutory tariff presets.

Each named CostLine has one Decimal rate whose unit is determined by its base:

- TURNOVER: fraction multiplied by fill price and quantity.
- UNITS: money per unit multiplied by fill quantity.
- ORDER: money per fill, including every partial fill.
- CHARGES: fraction multiplied by the sum of the referenced lines' raw, clamped amounts.

Lines may select BUY, SELL, or BOTH. A line that does not apply to the fill side is
omitted from that fill's component breakdown and contributes zero when referenced by
a dependent CHARGES line. Dependency references are explicit, unique and validated
at schedule construction; cycles are rejected using deterministic topological order.

Minimum and maximum values clamp each applicable line's raw amount. Neither line
amounts nor dependency sums are rounded. The final sum for one fill is rounded once
using Decimal ROUND_HALF_EVEN at the schedule's explicit currency digits. This
rounding mode is a new QuantX policy for this schedule model, not an inherited
repository-wide currency convention.

## Raw components and booked fill total

ChargeBreakdown.total continues to mean the exact, unrounded sum of its components.
It must not be redefined to mean the booked amount. Schedule results additionally
carry rounded_total, the single rounded amount applied for that fill; applied_total
selects rounded_total when present and otherwise retains the legacy exact total.

A schedule-backed ExecutionReceipt stores one per_fill_charges breakdown for each
fill. Its fee equals the sum of those rounded per-fill totals. The legacy aggregate
charges field is left unset for these receipts because its established invariant
continues to require charges.total == fee. This preserves both raw line evidence and
the rounded fee actually applied to accounting.

The receipt's resolve_per_fill_fees() method is the shared allocation contract used
by PaperSession and HistoricalAccountStateTracker. It uses actual rounded per-fill
totals, permits unambiguous one-fill legacy fees and zero-fee multi-fill receipts,
and rejects a non-zero aggregate-only multi-fill fee. It never equal-splits an
aggregate fee. Cumulative observation receipts have no fill allocation.

Schedule currency is mandatory and must match the fill/account currency at the
paper-session or backtest accounting boundary. QuantX validates digits in the
technical range 0 through 18 to bound Decimal quantization work; this is not a
currency registry or a claim about every currency's conventional precision.
Backtests record all material schedule parameters in the existing
ExecutionConfiguration.charge_model identity. The
canonical parameter set includes currency, digits, rounding policy, source, model
version, every line's name/base/side/rate/minimum/maximum and its dependency references.
The schedule model ID is a deterministic hash of this canonical representation;
the full parameters remain in provenance.

The legacy ExecutionProfile.fee_rate path is retained. Its existing fractional
turnover formula is routed through an ExecutionProfileChargeAdapter that implements
the ChargeModel contract, preserving the legacy per-fill fee formula without
introducing a second charge calculation engine or schedule implementation.

Slippage remains separate from transaction-cost charges.

## Account and P&L integration

The aggregate charge still flows through the existing paths:

  ChargeBreakdown.total
          ↓
  ExecutionReceipt.fee
          ↓
  CashLedger fee outflow
          ↓
  FillAccounting fee record
          ↓
  HistoricalAccountStateSnapshot.fees
          ↓
  net P&L

C5 does not duplicate cash or P&L accounting. It strengthens the provenance and decomposition of the amount already consumed by those ledgers.

## Point-in-time and provenance boundary

A charge model is configuration, not an inferred fact.

The model ID, version, and provenance are retained with the calculated charge. A future India-specific schedule must be selected by an explicit version/effective-date mechanism outside this universal percentage model.

No current STT, GST, exchange transaction charge, stamp duty, brokerage tariff, or similar live rule is hardcoded here.

## Safety boundary

C5 is paper/research modeling only.

It does not:
- submit real orders;
- bypass the live trading gate;
- infer unknown broker charges;
- retry execution;
- turn UNKNOWN into PASS;
- make broker-specific tariff claims;
- introduce a live broker SDK into the core.

A future LIVE broker receipt can populate the same structured charge contract when authoritative broker evidence is available. Missing detail must remain missing rather than being reconstructed from a generic paper model.

## Deliberate deferrals

The following remain later slices:
- India venue/broker charge schedules with authoritative source/effective-date evidence;
- STT/GST/stamp/exchange/SEBI/DP/other market-specific rules;
- derivatives-specific settlement and charge bases;
- financing/overnight funding;
- daily charge accrual and tax-lot policy;
- multi-currency charge settlement.

These require explicit market/broker evidence and must not be guessed into the universal core.
