"""Single-use admission authorization for one LIVE broker submission.

``ExecutionOrchestrator._execute_live_transactional`` is the only
application-owned LIVE submission path. Before this boundary existed, that
method could be reached directly with a request, a broker, and a unit of
work, skipping the admission checks in ``ExecutionOrchestrator.execute``.
The capability implemented here closes that bypass: the admission section
of ``execute`` mints a :class:`LiveSubmissionAuthorization` only after
every required LIVE admission check has succeeded, and the transactional
path refuses to reserve or submit without a valid one for the exact same
request.

The authorization is deliberately not a boolean, a plain dataclass, or a
callback result: it carries a keyed digest over the bound request identity,
computed with the issuing orchestrator's per-instance random key. The key
never leaves the :class:`LiveSubmissionAuthorizer` that owns it, there is
no supported path that supplies or replaces that object, and
verification recomputes the digest — so a missing, foreign, tampered,
mismatched, or replayed authorization is rejected exactly like a missing
one. The capability grants no new authority: it only records that this
orchestrator already admitted this request, and the trading gate remains
the authorization authority at reservation and submission time.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from dataclasses import dataclass
from secrets import token_bytes
from typing import Final
from uuid import UUID, uuid4

from quantx.domain.errors import QuantXError

# Domain-separation label for the keyed binding digest.
_BINDING_LABEL: Final = "quantx:live-submission-authorization:v1"

# Fixed, sanitized rejection reasons. A contract violation must never echo a
# foreign or attacker-supplied value back to the caller.
_MISSING_AUTHORIZATION_REASON: Final = "live submission did not present an admission authorization"
_MISMATCHED_AUTHORIZATION_REASON: Final = (
    "presented admission authorization does not match the request being submitted"
)
_REPLAYED_AUTHORIZATION_REASON: Final = (
    "presented admission authorization was already used for one submission"
)


class LiveSubmissionAuthorizationError(QuantXError):
    """Raised when a LIVE submission lacks a valid admission authorization.

    Raised before any durable reservation or broker contact, so the
    transactional path fails closed on every unauthorized entry: a missing
    capability, a hand-built or foreign value, a digest that does not
    verify, or a replay of an already-used capability.
    """


@dataclass(frozen=True, slots=True)
class LiveSubmissionAuthorization:
    """Single-use proof that one approved request passed LIVE submit admission.

    ``authorization_id`` is the nonce that makes the credential single-use;
    ``client_order_id`` and ``request_fingerprint`` bind it to the exact
    admitted request (the canonical fingerprint already covers the account,
    connection, market, execution mode, and execution semantics); ``proof``
    is the keyed digest only the issuing orchestrator can compute.

    The dataclass constructor is intentionally plain: a correctly shaped
    value built by any other means carries a proof that does not verify
    against the issuing orchestrator's key and is therefore rejected. The
    capability is a relay of an admission that already happened, never an
    independent grant of submission authority.
    """

    authorization_id: UUID
    client_order_id: UUID
    request_fingerprint: str
    proof: str


class LiveSubmissionAuthorizer:
    """Mints and verifies single-use LIVE submit authorizations.

    Holds a per-instance random key plus the set of consumed authorization
    identities. The key never leaves this object and there is no supported
    path that replaces it, so an authorization minted here verifies only
    against this same instance. Verification is constant-time over the
    keyed digest and rejects any binding mismatch; consumption is atomic,
    so a replayed authorization cannot authorize a second submission. The
    consumed set is process-local and grows only with LIVE execution
    attempts of this orchestrator, which already leave durable evidence;
    it is not a durable record and grants nothing across processes.
    """

    def __init__(self) -> None:
        self._key = token_bytes(32)
        self._lock = threading.RLock()
        self._consumed: set[UUID] = set()

    def issue(
        self,
        *,
        client_order_id: UUID,
        request_fingerprint: str,
    ) -> LiveSubmissionAuthorization:
        """Mint one authorization bound to the admitted request identity."""
        authorization_id = uuid4()
        return LiveSubmissionAuthorization(
            authorization_id=authorization_id,
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
            proof=self._digest(authorization_id, client_order_id, request_fingerprint),
        )

    def authorize(
        self,
        authorization: object,
        *,
        client_order_id: UUID,
        request_fingerprint: str,
    ) -> None:
        """Verify ``authorization`` for this exact request or fail closed.

        Raises :class:`LiveSubmissionAuthorizationError` when the value is
        absent or of an unsupported type, when its proof does not verify,
        when its binding does not match the request being submitted, or
        when the credential was already consumed. The identity is marked
        consumed only after every check passes, so a rejected value never
        occupies the single-use set.
        """
        if type(authorization) is not LiveSubmissionAuthorization:
            raise LiveSubmissionAuthorizationError(_MISSING_AUTHORIZATION_REASON)
        bound_authorization: LiveSubmissionAuthorization = authorization
        # Runtime type enforcement: the dataclass annotations are not
        # checked at construction, so a hostile value can carry a non-UUID
        # order identity or a non-string proof. Such a value is a binding
        # mismatch (fail closed), never a TypeError escaping the caller.
        if (
            type(bound_authorization.client_order_id) is not UUID
            or type(bound_authorization.request_fingerprint) is not str
            or type(bound_authorization.proof) is not str
        ):
            raise LiveSubmissionAuthorizationError(_MISMATCHED_AUTHORIZATION_REASON)
        with self._lock:
            if bound_authorization.authorization_id in self._consumed:
                raise LiveSubmissionAuthorizationError(_REPLAYED_AUTHORIZATION_REASON)
        expected = self._digest(
            bound_authorization.authorization_id,
            bound_authorization.client_order_id,
            bound_authorization.request_fingerprint,
        )
        if (
            not hmac.compare_digest(bound_authorization.proof, expected)
            or bound_authorization.client_order_id != client_order_id
            or bound_authorization.request_fingerprint != request_fingerprint
        ):
            raise LiveSubmissionAuthorizationError(_MISMATCHED_AUTHORIZATION_REASON)
        with self._lock:
            if bound_authorization.authorization_id in self._consumed:
                # Lost a race against a concurrent verifier of the same
                # credential: the first consumption wins authoritatively.
                raise LiveSubmissionAuthorizationError(_REPLAYED_AUTHORIZATION_REASON)
            self._consumed.add(bound_authorization.authorization_id)

    def _digest(
        self,
        authorization_id: UUID,
        client_order_id: UUID,
        request_fingerprint: str,
    ) -> str:
        message = "\x1f".join(
            (
                _BINDING_LABEL,
                str(authorization_id),
                str(client_order_id),
                request_fingerprint,
            )
        ).encode("utf-8")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()
