"""Application-owned trust boundary for LIVE risk-evidence sources.

A source is never trusted because it implements a protocol, returns a valid
dataclass, declares every required field, or echoes configured identities. It
is trusted only when the deployment registered a construction path for its
broker in this catalog and the catalog itself built the source over the exact
account/connection the process registered.

The catalog is composition state, not source state: it holds builders keyed by
broker id, calls the allowlisted builder with the process's registered
connection, validates the returned binding, and mints a sealed grant. The
authority in :mod:`quantx.application.live_risk` accepts only that grant, and
derives the expected account, connection, broker client and transport from the
builder's own binding instead of from caller-supplied values.

This module is vendor-neutral: it names no broker plugin and imports no broker
SDK. Concrete plugins register their construction path from their own module.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.account_registry import RegisteredConnection

from .live_risk_evidence import LiveRiskEvidenceSource


@dataclass(frozen=True, slots=True)
class TrustedLiveRiskEvidenceBinding:
    """The exact source and identity a sanctioned builder bound together.

    A builder owns its transport, broker client id and instrument mapping, so
    these values are produced by the construction path rather than supplied
    next to the source.
    """

    source: LiveRiskEvidenceSource
    account_id: AccountId
    broker_connection_id: BrokerConnectionId
    broker_client_id: str
    transport: object


@dataclass(frozen=True, slots=True)
class LiveRiskEvidenceSourceBuilder:
    """One application-registered construction path for one broker.

    Registration is an explicit composition act by the deployment. A builder
    is a module-level factory of the owning plugin; it is never derived from a
    source instance.
    """

    broker_id: str
    build: Callable[[RegisteredConnection], TrustedLiveRiskEvidenceBinding]

    def __post_init__(self) -> None:
        if type(self.broker_id) is not str or not self.broker_id.strip():
            raise ValueError("LIVE risk evidence builder requires a broker id")
        if not callable(self.build):
            raise ValueError("LIVE risk evidence builder requires a construction callable")


@dataclass(frozen=True, slots=True)
class LiveRiskEvidenceSourceGrant:
    """Application-minted proof that a catalog built this exact source.

    The seal covers the construction path, the binding identity and the exact
    source/transport objects, so a swapped binding or a hand-built grant is
    rejected. It is not a model of source honesty: it only binds one source
    instance to the registered connection and client the deployment chose.
    """

    broker_id: str
    builder_module: str
    builder_qualname: str
    binding: TrustedLiveRiskEvidenceBinding
    seal: str = field(repr=False)


def _module_of(build: Callable[[RegisteredConnection], TrustedLiveRiskEvidenceBinding]) -> str:
    module = getattr(build, "__module__", None)
    return module if isinstance(module, str) else ""


def _qualname_of(build: Callable[[RegisteredConnection], TrustedLiveRiskEvidenceBinding]) -> str:
    qualname = getattr(build, "__qualname__", None)
    return qualname if isinstance(qualname, str) else ""


class LiveRiskEvidenceSourceCatalog:
    """Application-owned allowlist of trusted LIVE risk-evidence construction paths."""

    def __init__(self, *, builders: tuple[LiveRiskEvidenceSourceBuilder, ...]) -> None:
        if type(builders) is not tuple or not builders:
            raise TypeError("LIVE risk evidence catalog requires a builder tuple")
        registered: dict[str, LiveRiskEvidenceSourceBuilder] = {}
        for builder in builders:
            if type(builder) is not LiveRiskEvidenceSourceBuilder:
                raise TypeError(
                    "LIVE risk evidence catalog requires LiveRiskEvidenceSourceBuilder entries"
                )
            if builder.broker_id in registered:
                raise ValueError(
                    "LIVE risk evidence catalog contains a duplicate broker id: "
                    f"{builder.broker_id}"
                )
            registered[builder.broker_id] = builder
        self._builders = registered
        self._key = secrets.token_bytes(32)

    @property
    def broker_ids(self) -> frozenset[str]:
        """The brokers whose construction path this catalog sanctions."""
        return frozenset(self._builders)

    def grant(self, registered: RegisteredConnection) -> LiveRiskEvidenceSourceGrant | None:
        """Build and seal the registered construction path for one connection.

        Returns ``None`` for an unregistered broker, a disabled connection, a
        builder failure, or a binding that does not describe the connection it
        was built for. No caller-supplied source instance is accepted anywhere
        in this signature.
        """
        if type(registered) is not RegisteredConnection:
            return None
        if not registered.enabled:
            return None
        builder = self._builders.get(registered.ref.broker_id)
        if builder is None:
            return None
        try:
            binding = builder.build(registered)
        except Exception:
            return None
        if not self._binding_shape_is_valid(binding):
            return None
        if not self._binding_matches(binding, registered):
            return None
        module = _module_of(builder.build)
        qualname = _qualname_of(builder.build)
        return LiveRiskEvidenceSourceGrant(
            broker_id=builder.broker_id,
            builder_module=module,
            builder_qualname=qualname,
            binding=binding,
            seal=self._seal(builder.broker_id, module, qualname, binding),
        )

    def verify(self, grant: LiveRiskEvidenceSourceGrant) -> bool:
        """Prove this catalog minted ``grant`` for this exact source and binding."""
        if type(grant) is not LiveRiskEvidenceSourceGrant:
            return False
        builder = self._builders.get(grant.broker_id)
        if builder is None:
            return False
        module = _module_of(builder.build)
        qualname = _qualname_of(builder.build)
        if grant.builder_module != module or grant.builder_qualname != qualname:
            return False
        if not self._binding_shape_is_valid(grant.binding):
            return False
        expected = self._seal(grant.broker_id, module, qualname, grant.binding)
        return hmac.compare_digest(grant.seal, expected)

    def _binding_shape_is_valid(self, binding: object) -> bool:
        """Reject anything that is not a complete, exact builder result."""
        if type(binding) is not TrustedLiveRiskEvidenceBinding:
            return False
        if type(binding.account_id) is not AccountId:
            return False
        if type(binding.broker_connection_id) is not BrokerConnectionId:
            return False
        if type(binding.broker_client_id) is not str or not binding.broker_client_id.strip():
            return False
        if binding.transport is None:
            return False
        return isinstance(binding.source, LiveRiskEvidenceSource)

    def _binding_matches(
        self,
        binding: TrustedLiveRiskEvidenceBinding,
        registered: RegisteredConnection,
    ) -> bool:
        return (
            binding.account_id == registered.ref.account_id
            and binding.broker_connection_id == registered.ref.connection_id
        )

    def _seal(
        self,
        broker_id: str,
        module: str,
        qualname: str,
        binding: TrustedLiveRiskEvidenceBinding,
    ) -> str:
        message = "\x00".join(
            [
                broker_id,
                module,
                qualname,
                str(binding.account_id),
                str(binding.broker_connection_id),
                binding.broker_client_id,
                str(id(binding.source)),
                str(id(binding.transport)),
            ]
        ).encode("utf-8")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()


__all__ = [
    "LiveRiskEvidenceSourceBuilder",
    "LiveRiskEvidenceSourceCatalog",
    "LiveRiskEvidenceSourceGrant",
    "TrustedLiveRiskEvidenceBinding",
]
