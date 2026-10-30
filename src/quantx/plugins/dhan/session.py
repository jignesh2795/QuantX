"""Dhan access-token lifetime and authentication failure contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class DhanTokenLifetimeError(ValueError):
    """The configured Dhan access token cannot safely cover another operation."""


class DhanAuthenticationRejectedError(RuntimeError):
    """Dhan returned its documented invalid-or-expired-token error code."""

    code = "DH-901"

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"Dhan authentication rejected ({self.code}): client id or access token is invalid or expired during {operation}")


def require_minimum_token_lifetime(
    expires_at: datetime,
    *,
    now: datetime,
    minimum_remaining: timedelta,
) -> None:
    """Reject unknown-quality time inputs and insufficient token lifetime."""
    for name, value in (("expires_at", expires_at), ("now", now)):
        if not isinstance(value, datetime):
            raise DhanTokenLifetimeError(f"Dhan token {name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise DhanTokenLifetimeError(f"Dhan token {name} must be timezone-aware")
    if not isinstance(minimum_remaining, timedelta) or minimum_remaining <= timedelta(0):
        raise DhanTokenLifetimeError("Dhan minimum token lifetime must be positive")

    remaining = expires_at.astimezone(UTC) - now.astimezone(UTC)
    if remaining <= timedelta(0):
        raise DhanTokenLifetimeError("Dhan access token has expired")
    if remaining < minimum_remaining:
        raise DhanTokenLifetimeError(
            "Dhan access token has insufficient remaining lifetime"
        )


__all__ = [
    "DhanAuthenticationRejectedError",
    "DhanTokenLifetimeError",
    "require_minimum_token_lifetime",
]
