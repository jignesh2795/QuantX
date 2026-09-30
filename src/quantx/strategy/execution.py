"""Prepare validated strategy intents for execution without executing them.

This boundary converts a deployment-authorized strategy result into the
existing risk-approved execution request contract. It deliberately stops
before broker or paper execution so backtest, replay, paper, shadow, and live
adapters can share the same preparation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.enums import OrderSide
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, BrokerConstraint
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Candle, MarketDataEvent, Quote
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext, PolicyResult
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskDecision, RiskResult
from quantx.domain.strategy import SignalAction

from .deployment import StrategyExecutionDecision


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
    ) -> None:
        self._instrument_registry = instrument_registry
        self._risk_engine = risk_engine or PreTradeRiskEngine()
        self._policy_engine = policy_engine or ExecutionPolicyEngine()

    def prepare(
        self,
        decision: StrategyExecutionDecision,
        event: MarketDataEvent,
        financial_state: AccountFinancialState,
        *,
        policy_context: PolicyContext | None = None,
        broker_constraints: tuple[BrokerConstraint, ...] = (),
        reference_price: Decimal | None = None,
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

        risk = self._risk_engine.evaluate(
            intent,
            RiskContext(
                instrument=instrument,
                financial_state=financial_state,
                broker_constraints=broker_constraints,
                reference_price=effective_reference,
            ),
        )
        if risk.decision is not RiskDecision.APPROVE:
            return StrategyExecutionPreparation(decision, risk, None, None)

        policy = self._policy_engine.evaluate(intent, policy_context or PolicyContext())
        if not policy.approved:
            return StrategyExecutionPreparation(decision, risk, policy, None)

        request = ApprovedExecutionRequest(
            order=build_order_from_intent(intent),
            execution_context=context,
            risk_result=risk,
            policy_result=policy,
            required_margin=intent.required_margin,
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
