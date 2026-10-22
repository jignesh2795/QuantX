"""Canonical execution port contracts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import Instrument
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.ports.broker import (
    BrokerAdapter,
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
)

from .market_data import MarketSnapshot
from .receipts.models import ExecutionOutcome, ExecutionReceipt


class ExecutionPort(Protocol):
    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...


class LiveExecutionPort(Protocol):
    """Capability boundary for live execution adapters.

    Concrete broker SDKs must implement this contract in plugins. The core
    owns only the approved-request and receipt semantics; it does not know
    vendor SDK types, credentials, or transport details.

    Implementations are responsible for enforcing broker-specific capability
    checks and translating the canonical request/receipt contracts.
    """

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...


@runtime_checkable
class BrokerPort(BrokerAdapter, Protocol):
    """Canonical broker port consumed by application services.

    Execution-owned: ``submit``, ``cancel``, and ``reconcile`` return canonical
    execution receipts, so the port belongs with the receipt contract rather
    than with the neutral broker capability contracts. The generic adapter,
    capability, connection, and descriptor contracts remain in
    :mod:`quantx.ports.broker`; concrete brokers implement this port in
    plugins.
    """

    @property
    def descriptor(self) -> BrokerDescriptor: ...

    @property
    def connection(self) -> BrokerConnectionRef: ...

    def health(self) -> bool: ...

    def capabilities(self) -> CapabilitySet: ...

    def instrument(self, instrument_id: InstrumentId) -> Instrument | None: ...

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt: ...


class MarketDataExecutionPort(Protocol):
    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | Candle,
    ) -> ExecutionReceipt: ...


__all__ = [
    "BrokerPort",
    "ExecutionPort",
    "LiveExecutionPort",
    "MarketDataExecutionPort",
    "ExecutionOutcome",
    "ExecutionReceipt",
]
