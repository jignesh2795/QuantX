"""Prepare validated strategy intents for execution without executing them.

This boundary converts a deployment-authorized strategy result into the
existing risk-approved execution request contract. It deliberately stops
before broker or paper execution so backtest, replay, paper, shadow, and live
adapters can share the same preparation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from quantx.domain.deployment import ExecutionContext, StrategyDeployment
from quantx.domain.enums import OrderSide, PositionEffect
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, BrokerConstraint
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Candle, MarketDataEvent, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext, PolicyResult
from quantx.domain.position_effect import (
    PositionEffectPolicy,
    PositionEvidence,
    resolve_absent_position_effect,
    resolve_position_effect,
)
from quantx.domain.product_selection import ProductSelectionPolicy, resolve_request_product
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskDecision, RiskResult
from quantx.domain.strategy import SignalAction

from .deployment import StrategyExecutionDecision


def bind_deployment_context(intent: TradeIntent, deployment: StrategyDeployment) -> TradeIntent:
    """Attach the deployment's execution context to a strategy-produced intent.

    The deployment is the authority for account, portfolio, deployment
    identity, market, and execution mode. A rehearsal carries no broker
    connection, so the bound context records ``broker_connection_id=None``
    rather than inventing one. An intent that already carries a context
    must match the deployment exactly; conflicting deployment evidence is
    rejected, never silently overwritten.
    """
    bound = ExecutionContext(
        account_id=deployment.account_id,
        portfolio_id=deployment.portfolio_id,
        deployment_id=deployment.deployment_id,
        market=deployment.market,
        broker_connection_id=None,
        execution_mode=deployment.execution_mode,
    )
    if intent.execution_context is None:
        return replace(intent, execution_context=bound)
    if intent.execution_context != bound:
        raise ValueError("intent execution context does not match deployment")
    return intent


@dataclass(frozen=True, slots=True)
class StrategyExecutionPreparation:
    """Risk/policy evaluation and, when approved, an execution request."""

    decision: StrategyExecutionDecision
    risk_result: RiskResult | None
    policy_result: PolicyResult | None
    request: ApprovedExecutionRequest | None


class StrategyExecutionPreparer:
    """Turn a deployment-bound strategy result into an approved request."""

    def __init__(
        self,
        instrument_registry: InstrumentRegistry,
        *,
        risk_engine: PreTradeRiskEngine | None = None,
        policy_engine: ExecutionPolicyEngine | None = None,
        product_selection: ProductSelectionPolicy | None = None,
        position_effect_policy: PositionEffectPolicy | None = None,
    ) -> None:
        self._instrument_registry = instrument_registry
        self._risk_engine = risk_engine or PreTradeRiskEngine()
        self._policy_engine = policy_engine or ExecutionPolicyEngine()
        self._product_selection = product_selection
        self._position_effect_policy = position_effect_policy

    def prepare(
        self,
        decision: StrategyExecutionDecision,
        event: MarketDataEvent,
        financial_state: AccountFinancialState,
        *,
        policy_context: PolicyContext | None = None,
        broker_constraints: tuple[BrokerConstraint, ...] = (),
        reference_price: Decimal | None = None,
        position_evidence: PositionEvidence | None = None,
        position_evidence_max_age: timedelta | None = None,
        approval_instant: datetime | None = None,
    ) -> StrategyExecutionPreparation:
        self._validate_decision(decision, event)
        intent = decision.result.intent
        if intent is None:
            return StrategyExecutionPreparation(decision, None, None, None)

        instrument = self._instrument_registry.resolve(event.instrument)
        if instrument is None:
            raise ValueError(f"instrument metadata unavailable for {event.instrument}")

        if intent.execution_context is None:
            raise ValueError("execution context is required")
        context = intent.execution_context
        deployment = decision.deployment
        if context.account_id != deployment.account_id:
            raise ValueError("intent account does not match deployment")
        if context.portfolio_id != deployment.portfolio_id:
            raise ValueError("intent portfolio does not match deployment")
        if context.deployment_id != deployment.deployment_id:
            raise ValueError("intent deployment does not match deployment")
        if context.market != deployment.market:
            raise ValueError("intent market does not match deployment")
        if context.execution_mode is not deployment.execution_mode:
            raise ValueError("intent execution mode does not match deployment")

        effective_reference = reference_price
        if effective_reference is None:
            effective_reference = self._event_reference_price(event)

        # Resolution is part of preparation, not submission. Product and
        # position effect are fixed here, before the final risk/policy
        # decision, and the approved request is built from exactly these
        # immutable values. A failure stops approval and every later side
        # effect; no component resolves them again at broker submission.
        product, context = resolve_request_product(
            context,
            explicit_product=intent.product,
            policy=self._product_selection,
        )
        resolved_intent = replace(intent, product=product, execution_context=context)
        order = build_order_from_intent(resolved_intent)

        effective_position_effect: PositionEffect | None = None
        position_evidence_cut: datetime | None = None
        evidence: PositionEvidence | None = None
        evidence_max_age: timedelta | None = None
        approval: datetime | None = None
        if resolved_intent.position_effect in {PositionEffect.CLOSE, PositionEffect.AUTO}:
            evidence = position_evidence
            evidence_max_age = position_evidence_max_age
            if evidence_max_age is None:
                raise ValueError(
                    f"{resolved_intent.position_effect.value} position effect requires a "
                    "position evidence freshness policy"
                )
            approval = approval_instant
            resolution = resolve_position_effect(
                order,
                evidence=evidence,
                max_evidence_age=evidence_max_age,
                approval_instant=approval,
            )
            effective_position_effect = resolution.effective
            position_evidence_cut = resolution.evidence_cut
        else:
            if position_evidence is not None or position_evidence_max_age is not None:
                raise ValueError(
                    "position evidence is only valid for AUTO or CLOSE position effects"
                )
            if resolved_intent.position_effect is None:
                # An absent effect is not a universal default: it resolves
                # only through the versioned market-pack policy, which binds
                # its rule identity onto the execution context.
                resolution, context = resolve_absent_position_effect(
                    context,
                    product=product,
                    policy=self._position_effect_policy,
                )
                effective_position_effect = resolution.effective
                resolved_intent = replace(resolved_intent, execution_context=context)

        risk = self._risk_engine.evaluate(
            resolved_intent,
            RiskContext(
                instrument=instrument,
                financial_state=financial_state,
                broker_constraints=broker_constraints,
                reference_price=effective_reference,
                product=product,
                effective_position_effect=effective_position_effect,
                market_pack_id=context.market_pack_id,
                rule_version=context.rule_version,
            ),
        )
        if risk.decision is not RiskDecision.APPROVE:
            return StrategyExecutionPreparation(decision, risk, None, None)

        policy = self._policy_engine.evaluate(resolved_intent, policy_context or PolicyContext())
        if not policy.approved:
            return StrategyExecutionPreparation(decision, risk, policy, None)

        request = ApprovedExecutionRequest(
            order=order,
            execution_context=context,
            risk_result=risk,
            policy_result=policy,
            required_margin=resolved_intent.required_margin,
            product=product,
            position_effect=resolved_intent.position_effect,
            effective_position_effect=effective_position_effect,
            position_evidence_cut=position_evidence_cut,
            position_evidence=evidence,
            position_evidence_max_age=evidence_max_age,
            position_effect_approval_instant=approval,
        )
        return StrategyExecutionPreparation(decision, risk, policy, request)

    @staticmethod
    def _event_reference_price(event: MarketDataEvent) -> Decimal | None:
        payload = event.payload
        if isinstance(payload, Quote):
            if payload.last is not None:
                return payload.last
            return payload.mid or payload.ask or payload.bid
        if isinstance(payload, Candle):
            return payload.close
        raise TypeError(f"unsupported market-data payload: {type(payload).__name__}")

    @staticmethod
    def _validate_decision(
        decision: StrategyExecutionDecision,
        event: MarketDataEvent,
    ) -> None:
        deployment = decision.deployment
        signal = decision.result.signal
        if not deployment.enabled:
            raise ValueError("strategy deployment is disabled")
        if deployment.strategy_id != signal.strategy_id.value:
            raise ValueError("deployment strategy id does not match strategy signal")
        if deployment.strategy_version != signal.strategy_version:
            raise ValueError("deployment strategy version does not match strategy signal")
        if deployment.market.venue != event.instrument.venue:
            raise ValueError("deployment market venue does not match market event")
        if signal.instrument != event.instrument:
            raise ValueError("strategy result instrument does not match market event")
        intent = decision.result.intent
        if intent is None:
            return
        if intent.instrument != event.instrument:
            raise ValueError("strategy intent instrument does not match market event")
        if intent.strategy_id != deployment.strategy_id:
            raise ValueError("strategy intent id does not match deployment")
        if intent.strategy_version != deployment.strategy_version:
            raise ValueError("strategy intent version does not match deployment")
        if signal.action is SignalAction.BUY and intent.side is not OrderSide.BUY:
            raise ValueError("BUY signal must carry a BUY intent")
        if signal.action is SignalAction.SELL and intent.side is not OrderSide.SELL:
            raise ValueError("SELL signal must carry a SELL intent")
