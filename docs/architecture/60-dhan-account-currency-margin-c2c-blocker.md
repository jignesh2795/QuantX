# ADR 0060: Dhan Account Currency and Margin Authority — C2c Blocked

**Status:** Account base-currency persistence implemented; Dhan C1 financial-state and margin authority remains **BLOCKED**.
**Base:** `c545818d0c22bcdb320c420a1b3ed737ebf2d98b`
**Implementation branch:** `feat/slice-c2c-margin-currency-authority-v1`
**Validation:** Pending exact-SHA local validation. This ADR claims no test result.

## Context

C1 requires persisted account base currency to be bound to the exact account and broker connection, and requires complete `AccountFinancialState` and `MarginEvidence` values in that same currency. The canonical state includes cash balance, available cash, blocked cash, margin used, margin available, and buying power. These are not interchangeable fields: an amount available to trade cannot simply be renamed available margin, and an amount utilized during the day cannot be assumed to be the full current margin requirement.

At the C2b baseline, `Account.base_currency` already existed in the domain, but the repository had no SQLite account repository or durable account table. Dhan's funds and margin contract was reviewed against the [official DhanHQ v2 Funds & Margin documentation](https://dhanhq.co/docs/v2/funds/) and the pinned `dhanhq==2.2.0` source behavior.

## Verified provider semantics

### `GET /fundlimit`

The documented response includes `dhanClientId`, `availabelBalance`, `sodLimit`, `collateralAmount`, `receiveableAmount`, `utilizedAmount`, `blockedPayoutAmount`, and `withdrawableBalance`.

The field descriptions identify available balance as available amount to trade, `sodLimit` as start-of-day balance, `utilizedAmount` as amount utilized in the day, and the other values as collateral, receivable, payout-blocked, and withdrawable amounts. The schema has no currency field and no provider observation timestamp.

Consequently the endpoint does not by itself establish all C1 financial-state components or a safe conversion into them. In particular, this change does not invent:
- current cash balance or equity from `sodLimit`;
- a blocked-cash formula from payout/collateral/receivable fields;
- `margin_available` by renaming `availabelBalance`;
- `margin_used` by silently treating `utilizedAmount` as a complete margin ledger;
- buying power by adding collateral, receivables, margin, or leverage assumptions.

The existing SDK normalizer also discards the account identifier and most fund-limit fields. A future provider source must preserve and bind the returned `dhanClientId` to the configured connection before treating any amount as account-specific.

### Margin calculator — `POST /margincalculator` and `POST /margincalculator/multi`

The single-order endpoint reports an order's `totalMargin`, components, `availableBalance`, `insufficientBalance`, brokerage and leverage. It is an order-scoped margin calculation, not a declared account-wide current margin ledger.

The multi-order endpoint can include positions and open orders and returns `total_margin`, components, `currency: INR`, and hedge benefit. The documentation explicitly describes these values as **indicative and valid for the current trading session**. Its response does not supply the full C1 financial-state vector or prove a complete whole-account snapshot. Since C2b cannot currently produce a complete canonical position book and C2a cannot provide authoritative daily realized P&L, these calculations do not unblock C1 composition.

## Decision

This branch introduces durable account configuration:
- SQLite schema v9 includes an `accounts` table with account identity, owner, display name, role, and canonical three-letter uppercase `base_currency`.
- `SqliteAccountRepository.create/get` round-trip `Account` records. A duplicate account ID fails rather than overwriting its base currency. Changing base currency requires a separate governed migration; existing money is never silently relabeled.
- Historical schema versions 1–8 migrate to v9 and create the account table.

It also introduces `DhanFinancialAuthoritySource`, exposed through `DhanBrokerAdapter.financial_authority_assessment(account=..., assessed_at=...)`. It requires the configured account record and the exact connection to match, returns the persisted configured currency, and reports `UNAVAILABLE` with stable blocker codes. It performs no broker I/O and emits no `AccountFinancialState`, `MarginEvidence`, balances, or margin values. Callers should load the account via `SqliteAccountRepository` rather than reconstructing a currency value at the risk boundary.

The result is **C2c BLOCKED for Dhan**: persistence of the configured base currency is now available, but the verified provider contract does not establish complete, currency-bound account financial state or authoritative whole-account margin. No C1 financial conversion or margin evidence is fabricated.

## Unblock criteria

C2c can be reconsidered when the implementation supplies:
1. A persisted account record loaded by the composition root and bound to the exact registered broker connection.
2. A provider-reported or otherwise explicitly authoritative currency binding for every financial amount.
3. Provider-defined semantics and timestamps for each current financial-state field required by C1, without implicit arithmetic or inferred defaults.
4. Margin evidence whose scope and currency are explicit, whose timestamp is fresh, and whose required/available values are authoritative for the current account—not an unbound order estimate.
5. Preservation and verification of the broker account identifier returned by the provider.
6. Exact-SHA tests for persistence, migrations, scope mismatch, malformed values, and fail-closed behavior.

## Relationship to C2a/C2b and LIVE readiness

C2a remains **BLOCKED** under ADR 0058. C2b remains **BLOCKED** under ADR 0059. C2d pending-scope persistence, C2e durable concurrency admission, and end-to-end approval-binding enforcement remain separate prerequisites. `build_live_execution` continues to refuse production LIVE composition.

No Dhan credentials, broker I/O, orders, or LIVE trading were used.
