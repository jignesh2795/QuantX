# Transaction-Cost and Charges Fidelity

## Purpose

The transaction-cost contract separates:
- charge calculation;
- raw, named component breakdown;
- the rounded per-fill amount applied to accounting;
- model version and reproducibility provenance;
- aggregate receipt fees used by existing cash and accounting paths.

The universal core accepts caller-supplied models and schedules. It does not embed
broker tariffs, Indian statutory rates, exchange schedules, or inferred defaults.

## Canonical charge contract

`src/quantx/execution/charges.py` defines:

- `ChargeCalculationContext`: transaction value plus optional currency, side, unit
  price and quantity; the schedule model requires the complete fill context.
- `ChargeComponent`: one named, finite, non-negative Decimal line amount.
- `ChargeBreakdown`: immutable raw components, model identity/version/provenance,
  and an optional rounded per-fill total.
- `ChargeModel`: deterministic calculation protocol.
- `PercentageBpsChargeModel`: the existing generic turnover percentage model.
- `CostLine`, `CostSchedule` and `CostScheduleChargeModel`: caller-supplied,
  immutable per-fill cost schedules.

`ChargeBreakdown.total` always means the exact unrounded sum of its components.
It is not redefined as the booked amount. `rounded_total` is the optional amount
actually applied to one fill, and `applied_total` returns that rounded value when
present, otherwise the legacy raw total.

Exact Decimal summation uses sufficient local precision rather than silently
truncating raw components to the ambient Decimal context.

## Existing percentage model

The existing `fee_bps` configuration is represented by
`PercentageBpsChargeModel` when no explicit charge model is supplied:

```text
transaction_value = fill.quantity * fill.price
charge = transaction_value * rate_bps / 10000
```

This remains a compatibility model. It is not a broker tariff and does not acquire
the new schedule's currency rounding policy implicitly.

## Caller-supplied per-fill schedules

A `CostSchedule` is immutable and requires:
- an explicit currency;
- explicit currency digits;
- a non-empty caller-supplied source;
- at least one uniquely named cost line.

QuantX currently accepts a technical digit range of zero through eighteen to bound
Decimal quantization work. This is not a currency registry or a claim about every
currency's conventional precision.

Each `CostLine` has one Decimal `rate`. Its unit is determined by the line's base:

- `TURNOVER`: a fraction multiplied by fill price and quantity.
- `UNITS`: money per unit multiplied by fill quantity.
- `ORDER`: money per fill, including every partial fill.
- `CHARGES`: a fraction multiplied by the sum of the named dependency lines' raw,
  clamped amounts.

Lines may select `BUY`, `SELL` or `BOTH`. A line that does not apply to the fill
side is omitted from that fill's breakdown and contributes zero when referenced by
a dependent `CHARGES` line.

Dependency names must be unique and resolve to schedule lines. Forward references
are allowed; self-references and cycles are rejected during schedule construction.
Evaluation uses Kahn's topological algorithm with a stable line-name tie-break.
Schedule line order and dependency-list order are canonicalized for identity.

Minimum and maximum values clamp each applicable line's raw amount. The dependency
calculation uses those raw clamped values. No line or dependency amount is rounded.
The final sum for one fill is rounded once using Decimal `ROUND_HALF_EVEN` at the
schedule's explicit currency digits. This rounding mode is a new QuantX policy for
this schedule model, not an inherited repository-wide currency convention.

Applicable zero-valued lines remain in the breakdown. Negative rates and negative
line amounts are rejected, consistent with the existing non-negative charge
component contract. Side-filtered lines are omitted rather than emitted as zero
components.

## Receipt and accounting boundary

`ExecutionReceipt` preserves the existing aggregate `fee` field.

Two receipt shapes are supported:

1. Legacy aggregate charge: `charges` is present and its exact `total` must equal
   `receipt.fee`, preserving the existing invariant.
2. Schedule-backed per-fill charges: `per_fill_charges` is aligned by tuple position
   with `fills`; each breakdown retains raw components and its own `rounded_total`.
   The aggregate `charges` field is unset for this shape. `receipt.fee` equals the
   exact sum of rounded per-fill totals.

Per-fill breakdowns must have matching tuple length, explicit common currency,
common model identity/version, and rounded totals that reconcile exactly to the
receipt fee. Cumulative-observation receipts carry no per-fill breakdown.

The receipt's `resolve_per_fill_fees()` method is the shared allocation contract
used by `PaperSession` and `HistoricalAccountStateTracker`:

- schedule-backed receipts return the actual rounded amount for each fill;
- legacy one-fill aggregate fees are unambiguous;
- zero-fee multi-fill receipts resolve to zero for each fill;
- non-zero aggregate-only multi-fill receipts fail closed;
- cumulative observations with no fills have no per-fill allocation.

No equal-split fallback exists. The legacy optional one-fill fee override is retained
only where it does not contradict structured charge evidence.

The same resolved scalar fee is passed to the existing `FillAccounting` and
`CashLedger` APIs. Those ledgers remain the canonical accounting path; structured
charge breakdowns are not duplicated into a second ledger.

For schedule-backed paper accounting, schedule currency must match the approved
instrument currency and account cash currency. Historical tracking verifies the
resolved instrument currency. Backtests verify schedule currency against starting
capital currency before strategy evaluation.

## SQLite receipt persistence

The canonical SQLite receipt payload persists both aggregate `ChargeBreakdown`
values and per-fill breakdowns, including raw component amounts and
`rounded_total`. Decimal values are serialized as decimal strings.

Older payloads that do not contain these optional fields remain readable.
Empty charge fields are omitted when serializing legacy receipts so immutable
receipt payload comparison does not change merely because the schema gained
optional charge detail.

## Backtest provenance

Schedule parameters extend the existing
`ExecutionConfiguration.charge_model` `SimulationModelIdentity`. No separate
schedule provenance field is introduced.

The full canonical parameter tuple records currency, digits, rounding policy,
source, model version, and every line's name, base, side, rate, minimum, maximum
and dependencies. Decimal representations are retained exactly. The deterministic
schedule model ID is a SHA-256 digest of those canonical parameters; the digest
does not replace the full parameters in provenance.

Opaque charge models without a canonical material-parameter representation remain
rejected by backtest provenance validation.

## Legacy execution compatibility

The legacy
`ExecutionProfile.fee_rate -> FillSimulator -> PaperBroker -> PaperOrderExecutor`
path remains active and separate from `PaperSession`. It already computes a scalar
fee for each simulated fill.

`ExecutionProfileChargeAdapter` implements the canonical charge protocol while
preserving the existing fractional turnover formula exactly. The legacy path does
not use basis-point conversion, does not use the new schedule rounding policy, and
does not apply the fee twice. The legacy classes and caller contracts remain in place.

Slippage remains separate from transaction-cost charges.

## Safety boundary

This is caller-supplied paper/research cost modeling only. It does not:
- submit real orders or bypass the LIVE trading gate;
- infer unknown broker charges;
- embed current statutory or exchange tariffs;
- introduce a live broker SDK into the core;
- create a second accounting or P&L path;
- turn UNKNOWN into PASS.

## Deliberate deferrals

The following remain outside this generic per-fill schedule:
- India venue/broker charge schedules and authoritative tariff values;
- STT day-level aggregation and true-up;
- clearing, settlement, auction or VWAP engines;
- MWST ingestion;
- derivatives settlement or day-close charge aggregation;
- financing/overnight funding;
- multi-currency charge settlement.

These require separate scope and authoritative evidence. They must not be inferred
or guessed into the universal charge model.
