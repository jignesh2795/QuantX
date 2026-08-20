# QuantX Storage and Message Bus Abstractions

## Storage ports

QuantX should define stable ports for:

- event store
- market-data store
- state store
- backtest/result store
- artifact store

Initial local implementations may use SQLite/DuckDB/Parquet as appropriate. PostgreSQL, TimescaleDB and object storage may be added later without changing domain semantics.

## Message bus port

Define a transport-independent interface for publish/subscribe and request/reply.

Initial local implementation may be in-process. Redis, NATS, ZeroMQ or Kafka-style transports remain deployment choices rather than domain dependencies.

## Principle

Infrastructure changes must not require trading-domain rewrites.
