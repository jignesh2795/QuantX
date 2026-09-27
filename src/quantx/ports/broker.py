"""Broker adapter port contracts.

Concrete brokers implement this interface in plugins. Vendor SDK types and
credentials must remain outside this module.
"""

from __future__ import annotations

from typing import Protocol

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import Instrument
from quantx.execution.ports import ExecutionReceipt
from quantx.integrations.brokers import BrokerDescriptor, CapabilitySet


class BrokerPort(Protocol):
    @property
    def descriptor(self) -> BrokerDescriptor:
        ...

    def health(self) -> bool:
        ...

    def capabilities(self) -> CapabilitySet:
        ...

    def instrument(self, instrument_id: str) -> Instrument | None:
        ...

    def submit(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        ...

    def cancel(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        ...

    def reconcile(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        ...
