"""Canonical request fingerprinting for duplicate-submission protection."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from quantx.domain.execution_request import ApprovedExecutionRequest


def _canonical_decimal(value: Decimal) -> str:
    """Render finite Decimals independent of trailing-zero representation."""
    if not value.is_finite():
        return str(value)
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda x: str(x[0]))
        }
    return value


def request_fingerprint(request: ApprovedExecutionRequest) -> str:
    """Hash execution-relevant fields, excluding client-order identity and timestamps."""
    payload = {
        "instrument": str(request.order.instrument),
        "side": request.order.side.value,
        "order_type": request.order.order_type.value,
        "quantity": request.order.quantity,
        "limit_price": request.order.limit_price,
        "stop_price": request.order.stop_price,
        "time_in_force": request.order.time_in_force.value,
        "account_id": str(request.execution_context.account_id.value),
        "portfolio_id": request.execution_context.portfolio_id.value,
        "deployment_id": request.execution_context.deployment_id.value,
        "market_venue": request.execution_context.market.venue,
        "market_region": request.execution_context.market.region.value,
        "market_family": request.execution_context.market.family.value,
        "broker_connection_id": (
            str(request.execution_context.broker_connection_id.value)
            if request.execution_context.broker_connection_id is not None
            else None
        ),
        "execution_mode": request.execution_context.execution_mode.value,
        "required_capabilities": sorted(request.order.required_capabilities),
    }
    canonical = json.dumps(_json_value(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
