"""Deterministic India-market execution rules for orders.

This layer answers whether an order is semantically valid for the Indian
market/instrument described by an :class:`IndianInstrumentSpec`. Whether a
particular broker can execute it is a separate broker-capability question.

All arithmetic uses exact Decimals; floats, NaN/infinity, and booleans are
rejected rather than coerced. Checks run in a fixed order and every failure
is collected with a stable machine-readable code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from quantx.domain.enums import AssetClass, OrderType
from quantx.domain.orders import Order

from .domain import IndianInstrumentSpec, ProductType


class IndiaRuleDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class IndiaRuleCheck:
    name: str
    passed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class IndiaRuleResult:
    decision: IndiaRuleDecision
    reason: str
    checks: tuple[IndiaRuleCheck, ...] = ()


_SEGMENTS_BY_ASSET: tuple[tuple[AssetClass, str], ...] = (
    (AssetClass.EQUITY, "EQ"),
    (AssetClass.ETF, "EQ"),
    (AssetClass.FUTURE, "FO"),
    (AssetClass.OPTION, "FO"),
    (AssetClass.FX, "CD"),
    (AssetClass.COMMODITY, "COM"),
)


def _allowed_segments(asset_class: AssetClass) -> frozenset[str] | None:
    """Return the India-universal segments for an asset class, if known."""
    for candidate, segment in _SEGMENTS_BY_ASSET:
        if asset_class is candidate:
            return frozenset({segment})
    return None


# India-universal product compatibility. Anything not listed here is left
# to broker capability/policy rather than hard-coded: fail closed.
_PRODUCT_ASSETS: tuple[tuple[ProductType, frozenset[AssetClass]], ...] = (
    (ProductType.CNC, frozenset({AssetClass.EQUITY, AssetClass.ETF})),
    (ProductType.DELIVERY, frozenset({AssetClass.EQUITY, AssetClass.ETF})),
    (ProductType.NRML, frozenset({AssetClass.FUTURE, AssetClass.OPTION})),
)

_MIS_ASSETS: frozenset[AssetClass] = frozenset(
    {AssetClass.EQUITY, AssetClass.ETF, AssetClass.FUTURE, AssetClass.OPTION}
)


def _mis_allowed(asset_class: AssetClass) -> bool:
    """MIS carries intraday semantics wherever the India policy permits it."""
    return asset_class in _MIS_ASSETS


_Check = Callable[[str, str], None]


def _product_allowed(product: ProductType, asset_class: AssetClass) -> bool:
    if product is ProductType.MIS:
        return _mis_allowed(asset_class)
    for candidate, assets in _PRODUCT_ASSETS:
        if product is candidate:
            return asset_class in assets
    return False


def _is_number(value: object) -> Decimal | None:
    """Return a finite Decimal for explicit numeric input, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    return None


class IndiaExecutionRuleEngine:
    """Validate an order against canonical Indian instrument metadata."""

    def validate(
        self,
        spec: IndianInstrumentSpec,
        order: Order,
        *,
        product: ProductType | None = None,
    ) -> IndiaRuleResult:
        """Run every India rule in fixed order, collecting all violations."""
        violations: list[str] = []
        checks: list[IndiaRuleCheck] = []

        def reject(name: str, message: str) -> None:
            violations.append(message)
            checks.append(IndiaRuleCheck(name, False, message))

        def accept(name: str, message: str) -> None:
            checks.append(IndiaRuleCheck(name, True, message))

        self._check_order_type(order, reject, accept)
        self._check_quantity(spec, order, reject, accept)
        self._check_ticks(spec, order, reject, accept)
        self._check_derivative_metadata(spec, reject, accept)
        self._check_segment(spec, reject, accept)
        if product is not None:
            self._check_product(spec, product, reject, accept)

        if violations:
            return IndiaRuleResult(
                IndiaRuleDecision.REJECT, "; ".join(violations), tuple(checks)
            )
        return IndiaRuleResult(
            IndiaRuleDecision.APPROVE, "india execution rules passed", tuple(checks)
        )

    @staticmethod
    def _check_order_type(order: Order, reject: _Check, accept: _Check) -> None:
        if order.order_type not in {
            OrderType.MARKET,
            OrderType.LIMIT,
            OrderType.STOP,
            OrderType.STOP_LIMIT,
        }:
            reject(
                "order_type",
                f"INDIA_ORDER_TYPE_INVALID: unsupported order type {order.order_type!r}",
            )
        else:
            accept("order_type", "order type is supported")

    @staticmethod
    def _check_quantity(
        spec: IndianInstrumentSpec, order: Order, reject: _Check, accept: _Check
    ) -> None:
        quantity = _is_number(order.quantity)
        lot_size = _is_number(spec.lot_size)
        if quantity is None or quantity <= 0:
            reject(
                "quantity",
                "INDIA_QUANTITY_INVALID: quantity must be a positive number",
            )
            return
        if lot_size is None or lot_size <= 0:
            reject(
                "quantity",
                "INDIA_LOT_SIZE_INVALID: instrument lot size is invalid",
            )
            return
        if quantity % lot_size != 0:
            reject(
                "quantity",
                f"INDIA_LOT_SIZE_INVALID: quantity {quantity} is not a multiple "
                f"of lot size {lot_size}",
            )
        else:
            accept("quantity", "quantity respects lot size")

    @staticmethod
    def _check_ticks(
        spec: IndianInstrumentSpec, order: Order, reject: _Check, accept: _Check
    ) -> None:
        tick_size = _is_number(spec.tick_size)
        prices: tuple[tuple[str, Decimal | None], ...] = ()
        if order.order_type is OrderType.LIMIT:
            prices = (("limit_price", order.limit_price),)
        elif order.order_type is OrderType.STOP:
            prices = (("stop_price", order.stop_price),)
        elif order.order_type is OrderType.STOP_LIMIT:
            prices = (
                ("limit_price", order.limit_price),
                ("stop_price", order.stop_price),
            )
        if not prices:
            accept("price_tick", "market order requires no price tick validation")
            return
        if tick_size is None or tick_size <= 0:
            reject(
                "price_tick",
                "INDIA_PRICE_TICK_INVALID: instrument tick size is invalid",
            )
            return
        for name, price in prices:
            number = _is_number(price)
            if number is None or number % tick_size != 0:
                reject(
                    "price_tick",
                    f"INDIA_PRICE_TICK_INVALID: {name} {price!r} is not a multiple "
                    f"of tick size {tick_size}",
                )
                return
        accept("price_tick", "prices align to tick size")

    @staticmethod
    def _check_derivative_metadata(
        spec: IndianInstrumentSpec, reject: _Check, accept: _Check
    ) -> None:
        if spec.asset_class in {AssetClass.FUTURE, AssetClass.OPTION}:
            try:
                spec.to_contract()
            except ValueError as exc:
                reject(
                    "derivative_metadata",
                    f"INDIA_DERIVATIVE_METADATA_INVALID: {exc}",
                )
            else:
                accept("derivative_metadata", "derivative metadata is coherent")
        elif (
            spec.expiry is not None
            or spec.underlying is not None
            or spec.strike is not None
            or spec.option_type is not None
        ):
            reject(
                "derivative_metadata",
                "INDIA_DERIVATIVE_METADATA_INVALID: non-derivative instrument "
                "carries derivative metadata",
            )
        else:
            accept("derivative_metadata", "no derivative metadata present")

    @staticmethod
    def _check_segment(spec: IndianInstrumentSpec, reject: _Check, accept: _Check) -> None:
        allowed = _allowed_segments(spec.asset_class)
        if allowed is None:
            reject(
                "segment",
                f"INDIA_SEGMENT_INVALID: no India-universal segment is defined "
                f"for asset class {spec.asset_class.value}",
            )
        elif spec.segment.value not in allowed:
            reject(
                "segment",
                f"INDIA_SEGMENT_INVALID: asset class {spec.asset_class.value} "
                f"must not use segment {spec.segment.value}",
            )
        else:
            accept("segment", "exchange segment is coherent")

    @staticmethod
    def _check_product(
        spec: IndianInstrumentSpec, product: ProductType, reject: _Check, accept: _Check
    ) -> None:
        if _product_allowed(product, spec.asset_class):
            accept("product", f"product {product.value} is compatible")
        else:
            reject(
                "product",
                f"INDIA_PRODUCT_INVALID: product {product.value} is not compatible "
                f"with asset class {spec.asset_class.value}",
            )


__all__ = [
    "IndiaExecutionRuleEngine",
    "IndiaRuleCheck",
    "IndiaRuleDecision",
    "IndiaRuleResult",
]
