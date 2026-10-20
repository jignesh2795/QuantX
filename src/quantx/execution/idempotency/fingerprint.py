"""Canonical request fingerprinting for duplicate-submission protection."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
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


def _canonical_datetime(value: datetime) -> str:
    """Render one instant deterministically regardless of its UTC offset.

    Evidence cuts are instants, not wall-clock spellings: the same instant
    observed as ``+05:30`` or ``Z`` must fingerprint identically. Fixed
    microsecond precision also keeps replay/serialization round-trips stable.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fingerprint timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _timedelta_microseconds(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, timedelta):
        raise TypeError("position evidence max age must be a timedelta or None")
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


def request_fingerprint(request: ApprovedExecutionRequest) -> str:
    """Hash execution-relevant fields, excluding client-order identity.

    Wall-clock construction timestamps stay excluded. The position-evidence
    cut and the approval instant are not construction timestamps: they are
    the approval evidence the resolved effect is bound to, so they
    participate in identity.
    """
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
        "product": None if request.product is None else str(request.product),
        "position_effect": (
            None if request.position_effect is None else request.position_effect.value
        ),
        "effective_position_effect": (
            None
            if request.effective_position_effect is None
            else request.effective_position_effect.value
        ),
        "market_pack_id": request.execution_context.market_pack_id,
        "rule_version": request.execution_context.rule_version,
        "position_evidence_cut": (
            None
            if request.position_evidence_cut is None
            else _canonical_datetime(request.position_evidence_cut)
        ),
        "position_effect_approval_instant": (
            None
            if request.position_effect_approval_instant is None
            else _canonical_datetime(request.position_effect_approval_instant)
        ),
        "position_evidence": (
            None
            if request.position_evidence is None
            else {
                "instrument": str(request.position_evidence.instrument),
                "quantity": request.position_evidence.quantity,
                "observed_at": _canonical_datetime(request.position_evidence.observed_at),
                "evidence_cut": _canonical_datetime(request.position_evidence.evidence_cut),
                "matched": request.position_evidence.matched,
            }
        ),
        "position_evidence_max_age_microseconds": _timedelta_microseconds(
            request.position_evidence_max_age
        ),
        "product_resolution": (
            None if request.product_resolution is None else request.product_resolution.to_payload()
        ),
        "position_effect_policy_resolution": (
            None
            if request.position_effect_policy_resolution is None
            else request.position_effect_policy_resolution.to_payload()
        ),
    }
    canonical = json.dumps(_json_value(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
