"""Canonical verification of request proofs against trusted market-pack rules.

A product-selection or absent-position-effect proof is a *claim*: it names the
market, the product, the effect, and the market-pack/rule identity that
produced it. A claim can be written by any caller, so the claim never proves
its own authenticity. Authenticity is established here, against the versioned
policies a deployment composes as canonical configuration.

The verifier is deliberately explicit: it holds the policies the deployment
trusts, selects one by the market-pack and rule identity the proof names, and
fails closed when no trusted policy covers that identity, when the identity or
version disagrees, or when the trusted policy does not support the request
semantics. Nothing in this module knows any market's product vocabulary; the
rules stay in the market pack that owns them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .deployment import ExecutionContext
from .enums import PositionEffect
from .instrument_registry import InstrumentResolution, InstrumentResolutionResolver
from .orders import Order
from .position_effect import AbsentPositionEffectResolution, PositionEffectPolicy
from .product_selection import ProductSelectionPolicy, ProductSelectionResolution
from .value_objects import ProductCode


class ProofVerificationError(ValueError):
    """A request proof could not be verified against a trusted versioned rule."""


class VerifiableRequest(Protocol):
    """The request fields a proof verification depends on."""

    @property
    def order(self) -> Order: ...

    @property
    def execution_context(self) -> ExecutionContext: ...

    @property
    def product(self) -> ProductCode | None: ...

    @property
    def position_effect(self) -> PositionEffect | None: ...

    @property
    def effective_position_effect(self) -> PositionEffect | None: ...

    @property
    def product_resolution(self) -> ProductSelectionResolution | None: ...

    @property
    def position_effect_policy_resolution(self) -> AbsentPositionEffectResolution | None: ...

    @property
    def instrument_resolution(self) -> InstrumentResolution | None: ...


@dataclass(frozen=True, slots=True)
class MarketPackPolicyVerifier:
    """The versioned market-pack policies one deployment trusts.

    The verifier is the canonical seam between a request proof and the market
    pack that owns the rule. It holds no market vocabulary of its own and
    never invents a rule: a proof that names an identity no trusted policy
    covers is rejected, not interpreted.
    """

    product_selection_policies: tuple[ProductSelectionPolicy, ...] = ()
    position_effect_policies: tuple[PositionEffectPolicy, ...] = ()
    instrument_resolver: InstrumentResolutionResolver | None = None

    def __post_init__(self) -> None:
        if not all(
            isinstance(policy, ProductSelectionPolicy) for policy in self.product_selection_policies
        ):
            raise ValueError("product selection policies must be ProductSelectionPolicy")
        if not all(
            isinstance(policy, PositionEffectPolicy) for policy in self.position_effect_policies
        ):
            raise ValueError("position effect policies must be PositionEffectPolicy")
        product_identities = [
            (policy.market_pack_id, policy.rule_version)
            for policy in self.product_selection_policies
        ]
        if len(set(product_identities)) != len(product_identities):
            raise ValueError("product selection policies must have unique market-pack identities")
        effect_identities = [
            (policy.market_pack_id, policy.rule_version) for policy in self.position_effect_policies
        ]
        if len(set(effect_identities)) != len(effect_identities):
            raise ValueError("position effect policies must have unique market-pack identities")
        if self.instrument_resolver is not None and not callable(
            getattr(self.instrument_resolver, "resolve_at", None)
        ):
            raise ValueError("instrument resolver must implement resolve_at")

    def product_policy_for(self, market_pack_id: str, rule_version: str) -> ProductSelectionPolicy:
        """Return the trusted product policy for one identity, or fail closed."""
        for policy in self.product_selection_policies:
            if policy.market_pack_id == market_pack_id and policy.rule_version == rule_version:
                return policy
        raise ProofVerificationError(
            "no trusted product selection policy for market pack "
            f"{market_pack_id} rule version {rule_version}"
        )

    def position_effect_policy_for(
        self, market_pack_id: str, rule_version: str
    ) -> PositionEffectPolicy:
        """Return the trusted position-effect policy for one identity, or fail closed."""
        for policy in self.position_effect_policies:
            if policy.market_pack_id == market_pack_id and policy.rule_version == rule_version:
                return policy
        raise ProofVerificationError(
            "no trusted position-effect policy for market pack "
            f"{market_pack_id} rule version {rule_version}"
        )

    def verify_product_resolution(
        self,
        resolution: ProductSelectionResolution,
        *,
        execution_context: ExecutionContext,
    ) -> None:
        """Verify one product claim against the trusted policy for its identity."""
        if not isinstance(resolution, ProductSelectionResolution):
            raise ProofVerificationError("product selection resolution has an unsupported type")
        if resolution.market != execution_context.market:
            raise ProofVerificationError(
                "product selection resolution market does not match the execution context"
            )
        if resolution.market_pack_id != execution_context.market_pack_id:
            raise ProofVerificationError(
                "product selection resolution market-pack id does not match the execution context"
            )
        if resolution.rule_version != execution_context.rule_version:
            raise ProofVerificationError(
                "product selection resolution rule version does not match the execution context"
            )
        policy = self.product_policy_for(resolution.market_pack_id, resolution.rule_version)
        try:
            policy.verify_resolution(resolution)
        except ValueError as exc:
            raise ProofVerificationError(str(exc)) from exc

    def verify_absent_effect_resolution(
        self,
        resolution: AbsentPositionEffectResolution,
        *,
        execution_context: ExecutionContext,
        product: ProductCode | None,
    ) -> None:
        """Verify one absent-effect claim against the trusted policy for its identity."""
        if not isinstance(resolution, AbsentPositionEffectResolution):
            raise ProofVerificationError(
                "position-effect policy resolution has an unsupported type"
            )
        if resolution.market != execution_context.market:
            raise ProofVerificationError(
                "position-effect policy resolution market does not match the execution context"
            )
        if resolution.market_pack_id != execution_context.market_pack_id:
            raise ProofVerificationError(
                "position-effect policy resolution market-pack id does not match the "
                "execution context"
            )
        if resolution.rule_version != execution_context.rule_version:
            raise ProofVerificationError(
                "position-effect policy resolution rule version does not match the "
                "execution context"
            )
        if resolution.product != product:
            raise ProofVerificationError(
                "position-effect policy resolution product does not match the resolved product"
            )
        policy = self.position_effect_policy_for(resolution.market_pack_id, resolution.rule_version)
        try:
            policy.verify_resolution(resolution)
        except ValueError as exc:
            raise ProofVerificationError(str(exc)) from exc

    def verify_instrument_resolution(
        self,
        resolution: InstrumentResolution,
        *,
        instrument_id: str,
    ) -> None:
        """Verify one instrument/contract claim against the trusted PIT resolver.

        The claim names a canonical instrument and the rule/contract identity
        selected at one instant. Only the trusted resolver can authenticate it:
        the same instrument is resolved again at the recorded instant and the
        selected identities must agree exactly. A claim that omits derivative
        metadata, selects a different historical record, or contradicts the
        canonical instrument is rejected, never repaired.
        """
        if self.instrument_resolver is None:
            raise ProofVerificationError(
                "an instrument resolution requires a trusted point-in-time resolver"
            )
        if not isinstance(resolution, InstrumentResolution):
            raise ProofVerificationError("instrument resolution has an unsupported type")
        if str(resolution.instrument.instrument_id) != instrument_id:
            raise ProofVerificationError(
                "instrument resolution does not describe the executed instrument"
            )
        try:
            trusted = self.instrument_resolver.resolve_at(
                resolution.instrument.instrument_id, resolution.resolved_at
            )
        except Exception as exc:
            raise ProofVerificationError(str(exc)) from exc
        if trusted.instrument != resolution.instrument:
            raise ProofVerificationError(
                "instrument resolution contradicts the canonical instrument"
            )
        if trusted.identity_payload() != resolution.identity_payload():
            raise ProofVerificationError(
                "instrument resolution does not match the trusted point-in-time resolution"
            )

    def verify_request(self, request: VerifiableRequest) -> None:
        """Verify every proof one request carries, or fail closed.

        A request that resolves a product must carry a product proof that the
        trusted policy supports. A request with an absent position effect must
        carry an absent-effect proof that the trusted policy permits. A request
        that needs no proof (no product, an explicit effect) needs no policy.
        """
        context = request.execution_context
        product = request.product
        product_resolution = request.product_resolution
        instrument_resolution: InstrumentResolution | None = getattr(
            request, "instrument_resolution", None
        )
        if instrument_resolution is None:
            if self.instrument_resolver is not None:
                raise ProofVerificationError(
                    "a deployment with a point-in-time instrument resolver requires "
                    "an instrument resolution"
                )
        else:
            self.verify_instrument_resolution(
                instrument_resolution,
                instrument_id=str(request.order.instrument),
            )
        if product is None:
            if product_resolution is not None:
                raise ProofVerificationError(
                    "an absent product cannot carry a product selection resolution"
                )
        else:
            if product_resolution is None:
                raise ProofVerificationError(
                    "a resolved product requires a validated product selection resolution"
                )
            if product_resolution.product != product:
                raise ProofVerificationError(
                    "product selection resolution product does not match the resolved product"
                )
            self.verify_product_resolution(product_resolution, execution_context=context)

        effect_resolution = request.position_effect_policy_resolution
        if request.position_effect is not None:
            if effect_resolution is not None:
                raise ProofVerificationError(
                    "a position-effect policy resolution is only valid for an absent "
                    "position effect"
                )
        else:
            if effect_resolution is None:
                raise ProofVerificationError(
                    "an absent position effect requires a validated market-pack policy resolution"
                )
            if effect_resolution.effective is not request.effective_position_effect:
                raise ProofVerificationError(
                    "position-effect policy resolution does not match the resolved effective effect"
                )
            self.verify_absent_effect_resolution(
                effect_resolution,
                execution_context=context,
                product=product,
            )


__all__ = [
    "MarketPackPolicyVerifier",
    "ProofVerificationError",
    "VerifiableRequest",
]
