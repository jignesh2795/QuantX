"""Order-type and time-in-force capability matrix for Digital Assets spot."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.enums import OrderType, TimeInForce


@dataclass(frozen=True, slots=True)
class DigitalAssetOrderCapability:
    order_type: OrderType
    time_in_force: TimeInForce

    def __post_init__(self) -> None:
        if not isinstance(self.order_type, OrderType):
            raise TypeError("order_type must be an OrderType")
        if not isinstance(self.time_in_force, TimeInForce):
            raise TypeError("time_in_force must be a TimeInForce")


# Only combinations that the canonical contracts can represent honestly.
DIGITAL_ASSETS_SPOT_CAPABILITIES: frozenset[DigitalAssetOrderCapability] = frozenset(
    {
        DigitalAssetOrderCapability(OrderType.MARKET, TimeInForce.GTC),
        DigitalAssetOrderCapability(OrderType.LIMIT, TimeInForce.GTC),
    }
)


def supports_order(order_type: OrderType, time_in_force: TimeInForce) -> bool:
    return any(
        capability.order_type is order_type and capability.time_in_force is time_in_force
        for capability in DIGITAL_ASSETS_SPOT_CAPABILITIES
    )


__all__ = [
    "DIGITAL_ASSETS_SPOT_CAPABILITIES",
    "DigitalAssetOrderCapability",
    "supports_order",
]
