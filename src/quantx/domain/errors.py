"""Domain-level exceptions for QuantX.

The domain layer must remain independent of adapters, frameworks, databases,
and user interfaces. These exceptions provide stable failure categories for
higher layers to translate into API, CLI, or broker-specific responses.
"""


class QuantXError(Exception):
    """Base exception for all QuantX application/domain errors."""


class DomainError(QuantXError):
    """Base class for invalid domain state or operations."""


class ValidationError(DomainError):
    """Raised when a value object or domain entity violates an invariant."""


class OrderError(DomainError):
    """Raised when an order violates a lifecycle or state invariant."""


class StateTransitionError(DomainError):
    """Raised when an invalid state transition is requested."""


class ConfigurationError(QuantXError):
    """Raised when runtime configuration is invalid or incomplete."""


class IntegrationError(QuantXError):
    """Base class for failures crossing an external integration boundary."""


class ReconciliationError(IntegrationError):
    """Raised when external and local trading state cannot be reconciled."""


class IdempotencyError(IntegrationError):
    """Raised when an idempotent command cannot be safely resolved."""
