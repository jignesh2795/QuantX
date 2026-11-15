"""Order-type and time-in-force capability matrix for Digital Assets spot."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.enums import OrderType, TimeInForce


@dataclass(frozen=True, slots=True)
class DigitalAssetOrderCapability:
    order_type: OrderType
    time_in_force: TimeInForce | None

    def __post_init__(self) -> None:
        if not isinstance(self.order_type, OrderType):
            raise TypeError("order_type must be an OrderType")
        if self.time_in_force is not None and not isinstance(self.time_in_force, TimeInForce):
            raise TypeError("time_in_force must be a TimeInForce or None")


# Absence is a real capability value, not an invented TimeInForce enum member.
# These pairs must not be interpreted as a cross-product of supported sets.
DIGITAL_ASSETS_SPOT_CAPABILITIES: frozenset[DigitalAssetOrderCapability] = frozenset(
    {
        DigitalAssetOrderCapability(OrderType.MARKET, None),
        DigitalAssetOrderCapability(OrderType.LIMIT, TimeInForce.GTC),
    }
)


def supports_order(order_type: OrderType, time_in_force: TimeInForce | None) -> bool:
    capability = DigitalAssetOrderCapability(order_type, time_in_force)
    return capability in DIGITAL_ASSETS_SPOT_CAPABILITIES


__all__ = [
    "DIGITAL_ASSETS_SPOT_CAPABILITIES",
    "DigitalAssetOrderCapability",
    "supports_order",
]
