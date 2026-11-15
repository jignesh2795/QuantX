"""Deterministic Digital Assets spot rule records and fixtures.

These rules are market-specific and intentionally do not expand the universal
``Instrument`` contract. All financial and quantity values use exact ``Decimal``
values parsed from strings. Fixture data is locally authored and synthetic; it
is not a downloaded or live exchange rule snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from quantx.domain.enums import OrderType, TimeInForce
from quantx.domain.value_objects import InstrumentId


def _require_decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


def _require_positive_decimal(value: Any, name: str) -> Decimal:
    value = _require_decimal(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def parse_decimal(value: Any, name: str) -> Decimal:
    """Parse a finite Decimal from a string or Decimal; reject floats/bools."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{name} must not be a float or bool")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{name} must be a valid decimal string") from exc
    else:
        raise TypeError(f"{name} must be a string or Decimal")
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _require_tz(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class DigitalAssetSpotRule:
    """Immutable, versioned Digital Assets spot rule snapshot."""

    instrument_id: InstrumentId
    canonical_symbol: str
    venue_symbol: str
    base_asset: str
    quote_asset: str
    price_tick: Decimal
    quantity_min: Decimal
    quantity_max: Decimal
    quantity_step: Decimal
    min_notional: Decimal | None
    max_notional: Decimal | None
    reference_price_semantics: str
    trading_status: str
    supported_order_types: frozenset[OrderType]
    supported_time_in_force: frozenset[TimeInForce]
    market_pack_id: str
    rule_version: str
    rule_source: str
    source_payload_hash: str
    parser_version: str
    effective_from: datetime
    effective_to: datetime | None
    observed_at: datetime
    synthetic: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise TypeError("instrument_id must be an InstrumentId")
        if not self.canonical_symbol.strip():
            raise ValueError("canonical_symbol must not be empty")
        if not self.venue_symbol.strip():
            raise ValueError("venue_symbol must not be empty")
        if not self.base_asset.strip():
            raise ValueError("base_asset must not be empty")
        if not self.quote_asset.strip():
            raise ValueError("quote_asset must not be empty")
        if self.base_asset.strip().upper() == self.quote_asset.strip().upper():
            raise ValueError("base_asset and quote_asset must differ")
        _require_positive_decimal(self.price_tick, "price_tick")
        quantity_min = _require_positive_decimal(self.quantity_min, "quantity_min")
        quantity_max = _require_positive_decimal(self.quantity_max, "quantity_max")
        _require_positive_decimal(self.quantity_step, "quantity_step")
        if quantity_min > quantity_max:
            raise ValueError("quantity_min must not exceed quantity_max")
        if self.min_notional is not None:
            min_notional = _require_positive_decimal(self.min_notional, "min_notional")
        else:
            min_notional = None
        if self.max_notional is not None:
            max_notional = _require_positive_decimal(self.max_notional, "max_notional")
        else:
            max_notional = None
        if min_notional is not None and max_notional is not None and min_notional > max_notional:
            raise ValueError("min_notional must not exceed max_notional")
        if not self.reference_price_semantics.strip():
            raise ValueError("reference_price_semantics must not be empty")
        if not self.trading_status.strip():
            raise ValueError("trading_status must not be empty")
        if not isinstance(self.supported_order_types, frozenset) or not self.supported_order_types:
            raise TypeError("supported_order_types must be a non-empty frozenset")
        if any(not isinstance(item, OrderType) for item in self.supported_order_types):
            raise TypeError("supported_order_types must contain OrderType values")
        if (
            not isinstance(self.supported_time_in_force, frozenset)
            or not self.supported_time_in_force
        ):
            raise TypeError("supported_time_in_force must be a non-empty frozenset")
        if any(not isinstance(item, TimeInForce) for item in self.supported_time_in_force):
            raise TypeError("supported_time_in_force must contain TimeInForce values")
        if not self.market_pack_id.strip():
            raise ValueError("market_pack_id must not be empty")
        if not self.rule_version.strip():
            raise ValueError("rule_version must not be empty")
        if not self.rule_source.strip():
            raise ValueError("rule_source must not be empty")
        if not self.source_payload_hash.strip():
            raise ValueError("source_payload_hash must not be empty")
        if not self.parser_version.strip():
            raise ValueError("parser_version must not be empty")
        effective_from = _require_tz(self.effective_from, "effective_from")
        _require_tz(self.observed_at, "observed_at")
        if self.effective_to is not None:
            effective_to = _require_tz(self.effective_to, "effective_to")
            if effective_from >= effective_to:
                raise ValueError("effective_from must be before effective_to")
        if not isinstance(self.synthetic, bool):
            raise TypeError("synthetic must be a bool")

    @property
    def is_trading(self) -> bool:
        return self.trading_status.strip().upper() == "TRADING"

    def supports(self, order_type: OrderType, time_in_force: TimeInForce) -> bool:
        return (
            order_type in self.supported_order_types
            and time_in_force in self.supported_time_in_force
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id.to_payload(),
            "canonical_symbol": self.canonical_symbol,
            "venue_symbol": self.venue_symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "price_tick": str(self.price_tick),
            "quantity_min": str(self.quantity_min),
            "quantity_max": str(self.quantity_max),
            "quantity_step": str(self.quantity_step),
            "min_notional": None if self.min_notional is None else str(self.min_notional),
            "max_notional": None if self.max_notional is None else str(self.max_notional),
            "reference_price_semantics": self.reference_price_semantics,
            "trading_status": self.trading_status,
            "supported_order_types": sorted(item.value for item in self.supported_order_types),
            "supported_time_in_force": sorted(item.value for item in self.supported_time_in_force),
            "market_pack_id": self.market_pack_id,
            "rule_version": self.rule_version,
            "rule_source": self.rule_source,
            "source_payload_hash": self.source_payload_hash,
            "parser_version": self.parser_version,
            "effective_from": self.effective_from.astimezone(UTC).isoformat(
                timespec="microseconds"
            ),
            "effective_to": None
            if self.effective_to is None
            else self.effective_to.astimezone(UTC).isoformat(timespec="microseconds"),
            "observed_at": self.observed_at.astimezone(UTC).isoformat(
                timespec="microseconds"
            ),
            "synthetic": self.synthetic,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> DigitalAssetSpotRule:
        if not isinstance(payload, Mapping):
            raise ValueError("rule payload must be a mapping")
        required = {
            "instrument_id",
            "canonical_symbol",
            "venue_symbol",
            "base_asset",
            "quote_asset",
            "price_tick",
            "quantity_min",
            "quantity_max",
            "quantity_step",
            "min_notional",
            "max_notional",
            "reference_price_semantics",
            "trading_status",
            "supported_order_types",
            "supported_time_in_force",
            "market_pack_id",
            "rule_version",
            "rule_source",
            "source_payload_hash",
            "parser_version",
            "effective_from",
            "effective_to",
            "observed_at",
            "synthetic",
        }
        if set(payload) != required:
            raise ValueError("rule payload has unexpected or missing fields")
        order_types = payload["supported_order_types"]
        tifs = payload["supported_time_in_force"]
        if not isinstance(order_types, (list, tuple, set, frozenset)):
            raise ValueError("supported_order_types must be a sequence")
        if not isinstance(tifs, (list, tuple, set, frozenset)):
            raise ValueError("supported_time_in_force must be a sequence")
        def _parse_dt(value: Any, name: str) -> datetime | None:
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError(f"{name} must be an ISO timestamp string")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{name} must be a valid ISO timestamp") from exc
            return _require_tz(parsed, name)
        return cls(
            instrument_id=InstrumentId.from_payload(payload["instrument_id"]),
            canonical_symbol=str(payload["canonical_symbol"]),
            venue_symbol=str(payload["venue_symbol"]),
            base_asset=str(payload["base_asset"]),
            quote_asset=str(payload["quote_asset"]),
            price_tick=parse_decimal(payload["price_tick"], "price_tick"),
            quantity_min=parse_decimal(payload["quantity_min"], "quantity_min"),
            quantity_max=parse_decimal(payload["quantity_max"], "quantity_max"),
            quantity_step=parse_decimal(payload["quantity_step"], "quantity_step"),
            min_notional=None
            if payload["min_notional"] is None
            else parse_decimal(payload["min_notional"], "min_notional"),
            max_notional=None
            if payload["max_notional"] is None
            else parse_decimal(payload["max_notional"], "max_notional"),
            reference_price_semantics=str(payload["reference_price_semantics"]),
            trading_status=str(payload["trading_status"]),
            supported_order_types=frozenset(OrderType(item) for item in order_types),
            supported_time_in_force=frozenset(TimeInForce(item) for item in tifs),
            market_pack_id=str(payload["market_pack_id"]),
            rule_version=str(payload["rule_version"]),
            rule_source=str(payload["rule_source"]),
            source_payload_hash=str(payload["source_payload_hash"]),
            parser_version=str(payload["parser_version"]),
            effective_from=_parse_dt(payload["effective_from"], "effective_from"),  # type: ignore[arg-type]
            effective_to=_parse_dt(payload["effective_to"], "effective_to"),
            observed_at=_parse_dt(payload["observed_at"], "observed_at"),  # type: ignore[arg-type]
            synthetic=bool(payload["synthetic"]),
        )


def _synthetic_hash(name: str) -> str:
    return "synthetic-local:" + sha256(name.encode("utf-8")).hexdigest()[:16]


def _rule(
    *,
    instrument_id: InstrumentId,
    canonical_symbol: str,
    venue_symbol: str,
    base_asset: str,
    quote_asset: str,
    price_tick: str,
    quantity_min: str,
    quantity_max: str,
    quantity_step: str,
    min_notional: str | None,
    max_notional: str | None,
    trading_status: str = "TRADING",
) -> DigitalAssetSpotRule:
    observed = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    return DigitalAssetSpotRule(
        instrument_id=instrument_id,
        canonical_symbol=canonical_symbol,
        venue_symbol=venue_symbol,
        base_asset=base_asset,
        quote_asset=quote_asset,
        price_tick=parse_decimal(price_tick, "price_tick"),
        quantity_min=parse_decimal(quantity_min, "quantity_min"),
        quantity_max=parse_decimal(quantity_max, "quantity_max"),
        quantity_step=parse_decimal(quantity_step, "quantity_step"),
        min_notional=None if min_notional is None else parse_decimal(min_notional, "min_notional"),
        max_notional=None if max_notional is None else parse_decimal(max_notional, "max_notional"),
        reference_price_semantics="LAST_TRADED_PRICE",
        trading_status=trading_status,
        supported_order_types=frozenset({OrderType.MARKET, OrderType.LIMIT}),
        supported_time_in_force=frozenset({TimeInForce.GTC}),
        market_pack_id="global-digital-assets-spot",
        rule_version="digital-assets-spot-fixtures-v1",
        rule_source="QuantX locally authored synthetic fixture (not an exchange download)",
        source_payload_hash=_synthetic_hash(canonical_symbol),
        parser_version="digital-assets-spot-fixtures-v1",
        effective_from=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        effective_to=None,
        observed_at=observed,
        synthetic=True,
    )


BTC_USDT_SPOT_RULE = _rule(
    instrument_id=InstrumentId("BINANCE", "BTCUSDT"),
    canonical_symbol="BTC/USDT",
    venue_symbol="BTCUSDT",
    base_asset="BTC",
    quote_asset="USDT",
    price_tick="0.01",
    quantity_min="0.00001",
    quantity_max="9000",
    quantity_step="0.00001",
    min_notional="5",
    max_notional="9000000",
)

ETH_USDT_SPOT_RULE = _rule(
    instrument_id=InstrumentId("BINANCE", "ETHUSDT"),
    canonical_symbol="ETH/USDT",
    venue_symbol="ETHUSDT",
    base_asset="ETH",
    quote_asset="USDT",
    price_tick="0.01",
    quantity_min="0.0001",
    quantity_max="100000",
    quantity_step="0.0001",
    min_notional="5",
    max_notional="10000000",
)

DIGITAL_ASSET_SPOT_RULES = (BTC_USDT_SPOT_RULE, ETH_USDT_SPOT_RULE)


def rule_for_instrument(instrument_id: InstrumentId) -> DigitalAssetSpotRule | None:
    for rule in DIGITAL_ASSET_SPOT_RULES:
        if rule.instrument_id == instrument_id:
            return rule
    return None


def rule_for_symbol(symbol: str) -> DigitalAssetSpotRule | None:
    normalized = symbol.strip().upper()
    for rule in DIGITAL_ASSET_SPOT_RULES:
        if rule.canonical_symbol.upper() == normalized or rule.venue_symbol.upper() == normalized:
            return rule
    return None


__all__ = [
    "BTC_USDT_SPOT_RULE",
    "DIGITAL_ASSET_SPOT_RULES",
    "DigitalAssetSpotRule",
    "ETH_USDT_SPOT_RULE",
    "parse_decimal",
    "rule_for_instrument",
    "rule_for_symbol",
]
