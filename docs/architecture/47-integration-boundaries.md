# Integration Boundaries

## Purpose

The integration layer connects QuantX to external broker/venue systems without
leaking vendor SDK types into the domain or execution core.

## Ownership

```text
integrations/
├── brokers.py              # broker capability and adapter contracts
├── account_registry.py     # account/connection isolation
├── health.py               # operational health/capability evidence
├── routing.py              # account-safe connection selection
├── execution_adapter.py    # broker execution boundary
└── reconciliation/
    ├── account.py          # account financial-state reconciliation
    ├── positions.py        # position reconciliation
    └── orders.py           # broker/local order reconciliation
```

## Execution preconditions

Execution policy belongs to `execution/preconditions/`. Integrations provide
observed evidence; they do not decide that an order is safe merely because a
broker adapter exists.

```text
broker/account/health/reconciliation
                |
                v
        observed evidence
                |
                v
      execution/preconditions
                |
        +-------+-------+
        |       |       |
      READY  BLOCKED  UNKNOWN
```

Missing evidence remains `UNKNOWN` and cannot be treated as approval.

## Account isolation

Every broker connection is scoped by:

- `account_id`
- `connection_id`
- `broker_id`
- `market_context_id`

Routing must never fail over across accounts. A failover candidate must still
belong to the requested account and market context and must satisfy the
required broker capabilities.

## Market separation

The integration layer does not collapse India, Global, and Crypto into one
implicit market. The market context travels with the account connection and
routing request. Concrete venue/broker implementations remain replaceable
plugins.

## Capital policy

Integrations may report actual balances and explicit broker constraints. They
must not invent minimum capital, lot size, multiplier, or other constraints.
Unknown constraints remain unknown until authoritative evidence is available.
