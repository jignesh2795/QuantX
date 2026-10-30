"""Typed submission-preflight boundary for broker adapters.

Three mutually exclusive classes of ``submit`` failure exist on the
LIVE boundary, and the orchestrator must never conflate them:

- ``NOT_SUBMITTED`` — a deterministic adapter/preflight check (connection
  binding, instrument mapping, market rules, wire-request construction)
  failed *before* any external transport call was entered. The request
  never reached the broker. Adapters prove this by raising
  :class:`BrokerPreflightRejected`, and may raise it only from code paths
  that run strictly before the transport call; raising it after transport
  I/O has begun violates the adapter contract and misreports an uncertain
  submission as a known local rejection.

- ``BROKER_NOT_ACCEPTED`` — the transport call did occur, but the broker
  returned an authoritative protocol response that proves the order was not
  accepted (for example, an explicit authentication rejection before order
  processing). Only an exact, documented response contract may raise
  ``BrokerSubmissionRejected``; arbitrary HTTP errors, timeouts, or message
  text are not proof.
- ``SUBMISSION_UNKNOWN`` — the transport call may have started or its
  external response is ambiguous (timeout, transport exception, unknown
  broker status). Every other ``submit`` failure stays in this class.
  These outcomes remain UNKNOWN and are never automatically retried.

Both exception types are deliberately ``ValueError`` subclasses for
adapter-contract compatibility. Only the orchestrator consumes them as
typed proof for a durable not-submitted closure; this is never a human
operator decision.
"""

from __future__ import annotations


class BrokerPreflightRejected(ValueError):
    """A trusted adapter-proved, pre-transport local rejection.

    The adapter entered no external transport call for the request.
    """

class BrokerSubmissionRejected(ValueError):
    """An authoritative broker response proves that the order was not accepted.

    This is distinct from local preflight: transport I/O has occurred, but a
    documented broker response (never a generic HTTP failure) proves the order
    was rejected before acceptance. The orchestrator may close the reservation
    as NOT_SUBMITTED using a separate broker-response provenance value.
    """


__all__ = ["BrokerPreflightRejected", "BrokerSubmissionRejected"]
