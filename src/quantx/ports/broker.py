"""Broker adapter port contracts.

Concrete brokers implement this interface in plugins. Vendor SDK types and
credentials must remain outside this module.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import Instrument
from quantx.domain.value_objects import InstrumentId
from quantx.execution.ports import ExecutionReceipt
from quantx.integrations.brokers import (
    BrokerAdapter,
    BrokerConnectionRef,
    BrokerDescriptor,
    CapabilitySet,
)


@runtime_checkable
class BrokerPort(BrokerAdapter, Protocol):
    """Canonical broker port consumed by application services."""

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
