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
