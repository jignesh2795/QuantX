"""Typed submission-preflight boundary for broker adapters.

Exactly two mutually exclusive classes of ``submit`` failure exist on the
LIVE boundary, and the orchestrator must never conflate them:

- ``NOT_SUBMITTED`` — a deterministic adapter/preflight check (connection
  binding, instrument mapping, market rules, wire-request construction)
  failed *before* any external transport call was entered. The request
  never reached the broker. Adapters prove this by raising
  :class:`BrokerPreflightRejected`, and may raise it only from code paths
  that run strictly before the transport call; raising it after transport
  I/O has begun violates the adapter contract and misreports an uncertain
  submission as a known local rejection.

- ``SUBMISSION_UNKNOWN`` — the transport call may have started or its
  external response is ambiguous (timeout, transport exception, unknown
  broker status). Every other ``submit`` failure stays in this class,
  including untyped exceptions, because another adapter can raise a
  generic exception after external submission has begun. These outcomes
  remain UNKNOWN and are never automatically retried.

The typed exception is deliberately a ``ValueError`` so existing
adapter-contract callers that reject invalid requests keep working; the
orchestrator is the only consumer that treats it as the NOT_SUBMITTED
proof and durably closes the pending reservation as a typed
not-submitted closure (never as a human operator decision).
"""

from __future__ import annotations


class BrokerPreflightRejected(ValueError):
    """A trusted adapter-proved, pre-transport local rejection.

    Contract: the raising adapter must have entered no external transport
    call for the request. The orchestrator reports the outcome as a known
    local block (never an ambiguous remote submission), durably closes the
    pending reservation through the typed not-submitted resolution
    contract, and never fabricates a broker receipt, a human operator
    identity, or a retry of the request.
    """


__all__ = ["BrokerPreflightRejected"]
