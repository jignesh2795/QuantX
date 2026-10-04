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
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from quantx.domain.enums import AssetClass, OrderType
from quantx.domain.orders import Order

from .domain import IndianInstrumentSpec, ProductType
from .rule_data import IndiaVenueRuleSnapshot


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
    rule_set_version: str | None = None
    provenance: str | None = None
    evaluated_at: datetime | None = None
    compatibility_evaluated: bool = False


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
        """Run instrument/order validity rules in fixed order.

        This is the R1-B1 boundary: lot/tick/metadata/segment/product-matrix
        checks that need no venue rule snapshot.
        """
        identity = self._check_instrument_identity(spec, order)
        if identity is not None:
            return identity
        violations: list[str] = []
        checks: list[IndiaRuleCheck] = [
            IndiaRuleCheck(
                "instrument_identity",
                True,
                "specification instrument matches order instrument",
            )
        ]

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

    def validate_compatibility(
        self,
        spec: IndianInstrumentSpec,
        order: Order,
        *,
        product: ProductType | None,
        venue_rules: IndiaVenueRuleSnapshot,
        evaluated_at: datetime,
    ) -> IndiaRuleResult:
        """Evaluate B3 product/order compatibility against venue rule data.

        Runs the B1 instrument/order checks plus snapshot-governed checks
        (order-type set, time-in-force, quantity freeze, price band) in one
        fixed order. ``venue_rules`` and ``evaluated_at`` are required: any
        missing or incoherent rule data fails closed with
        ``INDIA_RULE_DATA_UNAVAILABLE`` instead of becoming approval.
        Product/segment coherence follows from the matrix plus the
        asset/segment checks, so no broker instrument-type strings are
        needed here.
        """
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            message = "INDIA_RULE_DATA_UNAVAILABLE: evaluation timestamp must be aware"
            check = IndiaRuleCheck("evaluation_timestamp", False, message)
            return IndiaRuleResult(
                IndiaRuleDecision.REJECT,
                message,
                (check,),
                venue_rules.version,
                venue_rules.provenance,
                evaluated_at,
                compatibility_evaluated=True,
            )
        identity = self._check_instrument_identity(spec, order)
        if identity is not None:
            return IndiaRuleResult(
                IndiaRuleDecision.REJECT,
                identity.reason,
                identity.checks,
                venue_rules.version,
                venue_rules.provenance,
                evaluated_at,
                compatibility_evaluated=True,
            )
        usable = venue_rules.effective_at <= evaluated_at
        violations: list[str] = []
        checks: list[IndiaRuleCheck] = [
            IndiaRuleCheck(
                "instrument_identity",
                True,
                "specification instrument matches order instrument",
            )
        ]

        def reject(name: str, message: str) -> None:
            violations.append(message)
            checks.append(IndiaRuleCheck(name, False, message))

        def accept(name: str, message: str) -> None:
            checks.append(IndiaRuleCheck(name, True, message))

        scope_failure = self._check_rule_scope(spec, venue_rules)
        if scope_failure is not None:
            return IndiaRuleResult(
                IndiaRuleDecision.REJECT,
                scope_failure,
                tuple(checks) + (IndiaRuleCheck("rule_scope", False, scope_failure),),
                venue_rules.version,
                venue_rules.provenance,
                evaluated_at,
                compatibility_evaluated=True,
            )
        checks.append(
            IndiaRuleCheck("rule_scope", True, "venue rule scope applies")
        )
        self._check_order_type(order, reject, accept)
        self._check_snapshot_order_type(order, venue_rules, usable, reject, accept)
        self._check_time_in_force(order, venue_rules, usable, reject, accept)
        self._check_quantity(spec, order, reject, accept)
        self._check_quantity_freeze(order, venue_rules, usable, reject, accept)
        self._check_ticks(spec, order, reject, accept)
        self._check_price_band(
            order, venue_rules, usable, evaluated_at, reject, accept
        )
        self._check_derivative_metadata(spec, reject, accept)
        self._check_segment(spec, reject, accept)
        if product is not None:
            self._check_product(spec, product, reject, accept)
            self._check_snapshot_product(product, venue_rules, usable, reject, accept)

        if violations:
            return IndiaRuleResult(
                IndiaRuleDecision.REJECT,
                "; ".join(violations),
                tuple(checks),
                venue_rules.version,
                venue_rules.provenance,
                evaluated_at,
                compatibility_evaluated=True,
            )
        return IndiaRuleResult(
            IndiaRuleDecision.APPROVE,
            "india product/order compatibility passed",
            tuple(checks),
            venue_rules.version,
            venue_rules.provenance,
            evaluated_at,
        )

    @staticmethod
    def _check_instrument_identity(
        spec: IndianInstrumentSpec, order: Order
    ) -> IndiaRuleResult | None:
        if spec.instrument_id == order.instrument:
            return None
        message = (
            "INDIA_INSTRUMENT_MISMATCH: specification instrument "
            f"{spec.instrument_id} does not match order instrument "
            f"{order.instrument}"
        )
        check = IndiaRuleCheck("instrument_identity", False, message)
        return IndiaRuleResult(IndiaRuleDecision.REJECT, message, (check,))

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

    @staticmethod
    def _check_rule_scope(
        spec: IndianInstrumentSpec, venue_rules: IndiaVenueRuleSnapshot
    ) -> str | None:
        """Return a rejection reason unless the snapshot scope applies.

        An absent or entirely empty scope is unknown and fails closed; any
        set scope field that disagrees with the evaluated specification is a
        scope mismatch. ``None`` means the scope applies.
        """
        scope = venue_rules.scope
        if scope is None or scope.is_unspecified():
            return "INDIA_RULE_DATA_UNAVAILABLE: venue rule scope is unknown"
        if scope.exchange is not None and scope.exchange is not spec.exchange:
            return (
                "INDIA_RULE_SCOPE_MISMATCH: venue rule scope exchange "
                f"{scope.exchange.value} does not apply to {spec.exchange.value}"
            )
        if scope.segment is not None and scope.segment is not spec.segment:
            return (
                "INDIA_RULE_SCOPE_MISMATCH: venue rule scope segment "
                f"{scope.segment.value} does not apply to {spec.segment.value}"
            )
        if scope.instrument_id is not None and scope.instrument_id != spec.instrument_id:
            return (
                "INDIA_RULE_SCOPE_MISMATCH: venue rule scope instrument "
                f"{scope.instrument_id} does not apply to {spec.instrument_id}"
            )
        return None

    @classmethod
    def _check_snapshot_order_type(
        cls,
        order: Order,
        venue_rules: IndiaVenueRuleSnapshot,
        usable: bool,
        reject: _Check,
        accept: _Check,
    ) -> None:
        if not usable or venue_rules.allowed_order_types is None:
            reject(
                "order_type_snapshot",
                "INDIA_RULE_DATA_UNAVAILABLE: venue allowed order types are unknown",
            )
        elif order.order_type not in venue_rules.allowed_order_types:
            reject(
                "order_type_snapshot",
                f"INDIA_ORDER_TYPE_INVALID: order type {order.order_type.value} "
                "is not permitted by the venue rule snapshot",
            )
        else:
            accept("order_type_snapshot", "order type is permitted by venue rules")

    @classmethod
    def _check_time_in_force(
        cls,
        order: Order,
        venue_rules: IndiaVenueRuleSnapshot,
        usable: bool,
        reject: _Check,
        accept: _Check,
    ) -> None:
        if not usable or venue_rules.allowed_time_in_force is None:
            reject(
                "time_in_force",
                "INDIA_RULE_DATA_UNAVAILABLE: venue allowed time-in-force set "
                "is unknown",
            )
        elif order.time_in_force not in venue_rules.allowed_time_in_force:
            reject(
                "time_in_force",
                f"INDIA_TIF_INVALID: time-in-force {order.time_in_force.value} "
                "is not permitted by the venue rule snapshot",
            )
        else:
            accept("time_in_force", "time-in-force is permitted by venue rules")

    @classmethod
    def _check_quantity_freeze(
        cls,
        order: Order,
        venue_rules: IndiaVenueRuleSnapshot,
        usable: bool,
        reject: _Check,
        accept: _Check,
    ) -> None:
        quantity = _is_number(order.quantity)
        if quantity is None:
            accept("quantity_freeze", "no valid quantity to freeze-check")
            return
        freeze = _is_number(venue_rules.quantity_freeze)
        if not usable or freeze is None or freeze <= 0:
            reject(
                "quantity_freeze",
                "INDIA_RULE_DATA_UNAVAILABLE: applicable quantity freeze is unknown",
            )
        elif quantity > freeze:
            reject(
                "quantity_freeze",
                f"INDIA_QUANTITY_FREEZE_INVALID: quantity {quantity} exceeds "
                f"freeze {freeze}",
            )
        else:
            accept("quantity_freeze", "quantity is within the freeze limit")

    @classmethod
    def _check_price_band(
        cls,
        order: Order,
        venue_rules: IndiaVenueRuleSnapshot,
        usable: bool,
        evaluated_at: datetime,
        reject: _Check,
        accept: _Check,
    ) -> None:
        prices: tuple[Decimal | None, ...] = ()
        if order.order_type is OrderType.LIMIT:
            prices = (order.limit_price,)
        elif order.order_type is OrderType.STOP:
            prices = (order.stop_price,)
        elif order.order_type is OrderType.STOP_LIMIT:
            prices = (order.limit_price, order.stop_price)
        if not prices:
            accept("price_band", "market order carries no band-governed price")
            return
        band = venue_rules.price_band
        lower = _is_number(band.lower_bound) if band is not None else None
        upper = _is_number(band.upper_bound) if band is not None else None
        band_usable = band is not None and band.effective_at <= evaluated_at
        if (
            not usable
            or not band_usable
            or lower is None
            or upper is None
            or lower > upper
        ):
            reject(
                "price_band",
                "INDIA_RULE_DATA_UNAVAILABLE: applicable price band is unknown",
            )
            return
        for price in prices:
            number = _is_number(price)
            if number is None:
                accept("price_band", "no valid price to band-check")
                return
            if number < lower or number > upper:
                reject(
                    "price_band",
                    f"INDIA_PRICE_BAND_INVALID: price {number} is outside "
                    f"[{lower}, {upper}]",
                )
                return
        accept("price_band", "prices are within the applicable band")

    @classmethod
    def _check_snapshot_product(
        cls,
        product: ProductType,
        venue_rules: IndiaVenueRuleSnapshot,
        usable: bool,
        reject: _Check,
        accept: _Check,
    ) -> None:
        if not usable or venue_rules.allowed_products is None:
            reject(
                "product_snapshot",
                "INDIA_RULE_DATA_UNAVAILABLE: venue allowed product set is unknown",
            )
        elif product not in venue_rules.allowed_products:
            reject(
                "product_snapshot",
                f"INDIA_PRODUCT_INVALID: product {product.value} is not permitted "
                "by the venue rule snapshot",
            )
        else:
            accept("product_snapshot", "product is permitted by venue rules")


__all__ = [
    "IndiaExecutionRuleEngine",
    "IndiaRuleCheck",
    "IndiaRuleDecision",
    "IndiaRuleResult",
]
