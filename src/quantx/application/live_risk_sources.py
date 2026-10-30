"""Application-owned trust boundary for LIVE risk-evidence sources.

A source is never trusted because it implements a protocol, returns a valid
dataclass, declares every required field, or echoes configured identities. It is
trusted only when the exact broker connection this process registered supplies
the source's construction path itself: the adapter held by
:class:`~quantx.integrations.account_registry.RegisteredConnection` implements
:class:`LiveRiskEvidenceSourceProvider`.

That anchor is deliberate. The object that builds risk evidence is the same
object the process registered for that connection's health, capability routing,
reconciliation and recovery observations, so replacing it means replacing the
broker connection rather than swapping only the numbers the risk engine reads.
There is no separate catalog input:
:class:`quantx.application.live_execution.LiveExecutionConfig` cannot carry one,
and the sanctioned factory creates the catalog from the registered adapter and
never returns it. The module-local constructor token is API encapsulation, not a
security boundary against arbitrary Python code executing in this process. Any
wrapper required for LIVE dispatch must itself be the registered adapter; a
separate wrapper around the registered object is intentionally rejected.

Python cannot distinguish "the deployment wired this" from "other code in this
same process wired this", so this boundary does not claim to sandbox arbitrary
in-process code. What it does guarantee is that no free-standing evidence
declaration exists: LIVE authority follows the registered execution path.

This module is vendor-neutral: it names no broker plugin and imports no broker
SDK. Concrete plugins implement the provider on their own adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.account_registry import RegisteredConnection

from .live_risk_evidence import LiveRiskEvidenceSource

# Module-local token gates ordinary constructor use. This is API encapsulation,
# not a sandbox against arbitrary Python code that can import underscored names.
_CONSTRUCTION_TOKEN = object()

_CATALOG_CONSTRUCTION_REASON = (
    "LIVE risk evidence catalog construction requires the application construction "
    "token from a registered broker connection"
)


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


@runtime_checkable
class LiveRiskEvidenceSourceProvider(Protocol):
    """A registered broker adapter that owns its LIVE risk-evidence source.

    The provider is the adapter, not a separate registration record: a
    deployment that wants LIVE authority must make the connection it registered
    for submission and reconciliation also responsible for the evidence that
    authorizes submission.
    """

    def build_live_risk_evidence_binding(
        self, registered: RegisteredConnection
    ) -> TrustedLiveRiskEvidenceBinding | None: ...


BuildLiveRiskEvidenceBinding = Callable[
    [RegisteredConnection], TrustedLiveRiskEvidenceBinding | None
]


@dataclass(frozen=True, slots=True)
class _LiveRiskEvidenceSourceBuilder:
    """One construction path, always a bound method of a registered adapter."""

    broker_id: str
    build: BuildLiveRiskEvidenceBinding

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


def _module_of(build: BuildLiveRiskEvidenceBinding) -> str:
    module = getattr(build, "__module__", None)
    return module if isinstance(module, str) else ""


def _qualname_of(build: BuildLiveRiskEvidenceBinding) -> str:
    qualname = getattr(build, "__qualname__", None)
    return qualname if isinstance(qualname, str) else ""


class LiveRiskEvidenceSourceCatalog:
    """Application-minted allowlist of LIVE risk-evidence construction paths.

    The supported public composition API does not expose catalog creation, and
    the constructor requires a module-local token. This is API encapsulation,
    not a sandbox against arbitrary in-process Python code. A catalog created by
    the sanctioned factory holds only the bound construction method of the
    registered broker adapter it was derived from.
    """

    def __init__(
        self,
        *,
        builders: tuple[_LiveRiskEvidenceSourceBuilder, ...],
        token: object | None = None,
    ) -> None:
        if token is not _CONSTRUCTION_TOKEN:
            raise TypeError(_CATALOG_CONSTRUCTION_REASON)
        if type(builders) is not tuple or not builders:
            raise TypeError("LIVE risk evidence catalog requires a builder tuple")
        registered: dict[str, _LiveRiskEvidenceSourceBuilder] = {}
        for builder in builders:
            if type(builder) is not _LiveRiskEvidenceSourceBuilder:
                raise TypeError("LIVE risk evidence catalog requires builder entries")
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
        if type(binding) is not TrustedLiveRiskEvidenceBinding:
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

    def verify_for_registered(
        self,
        grant: LiveRiskEvidenceSourceGrant,
        registered: RegisteredConnection,
    ) -> bool:
        """Verify a grant was built by the exact adapter in this registry entry.

        The ordinary verify method proves only that this catalog minted the
        grant. A catalog derived from another adapter can have the same broker
        method module/qualname and issue a valid grant for matching identifiers.
        The binding is valid for LIVE only when this catalog's bound construction
        method belongs to this exact registered adapter.
        """
        if type(registered) is not RegisteredConnection or not registered.enabled:
            return False
        if not self.verify(grant):
            return False
        builder = self._builders.get(registered.ref.broker_id)
        if builder is None:
            return False
        if getattr(builder.build, "__self__", None) is not registered.adapter:
            return False
        return (
            grant.broker_id == registered.ref.broker_id
            and self._binding_matches(grant.binding, registered)
        )

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


def live_risk_evidence_catalog_for(
    registered: RegisteredConnection,
) -> LiveRiskEvidenceSourceCatalog | None:
    """Derive the catalog for one registered connection, or ``None``.

    Returns ``None`` when the argument is not a registration, when the
    connection is disabled, or when its adapter exposes no construction path.
    The adapter's bound method *is* the construction path, so evidence a LIVE
    stack can authorize always comes from the object registered to submit and
    reconcile for that connection.
    """
    if type(registered) is not RegisteredConnection:
        return None
    if not registered.enabled:
        return None
    adapter = registered.adapter
    if not isinstance(adapter, LiveRiskEvidenceSourceProvider):
        return None
    builder = _LiveRiskEvidenceSourceBuilder(
        broker_id=registered.ref.broker_id,
        build=adapter.build_live_risk_evidence_binding,
    )
    return LiveRiskEvidenceSourceCatalog(builders=(builder,), token=_CONSTRUCTION_TOKEN)


__all__ = [
    "BuildLiveRiskEvidenceBinding",
    "LiveRiskEvidenceSourceCatalog",
    "LiveRiskEvidenceSourceGrant",
    "LiveRiskEvidenceSourceProvider",
    "TrustedLiveRiskEvidenceBinding",
    "live_risk_evidence_catalog_for",
]
