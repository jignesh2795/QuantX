"""Dhan transport boundary.

Only this module may import the third-party DhanHQ SDK.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from .mapping import decimal_field, extract_filled_quantity, parse_dhan_timestamp
from .models import (
    DhanCandleSnapshot,
    DhanCredentials,
    DhanFundsSnapshot,
    DhanOrderDetail,
    DhanOrderRequest,
    DhanOrderResponse,
    DhanPayload,
    DhanPositionSnapshot,
    DhanPositionsSnapshot,
    DhanQuoteSnapshot,
)


class DhanTimeoutError(Exception):
    """Raised when a Dhan transport call exceeds its configured timeout."""

    def __init__(self, operation: str, timeout: float) -> None:
        self.operation = operation
        self.timeout = timeout
        super().__init__(f"Dhan {operation} timed out after {timeout}s")


DEFAULT_READ_TIMEOUT_SECONDS = 10.0


@runtime_checkable
class DhanTransport(Protocol):
    """Dhan wire boundary.

    R0-B bounds only the safety-critical control path: ``submit``, ``cancel``,
    and ``reconcile`` take an explicit ``timeout``. The read-only observations
    (``health``, ``fund_limits``, ``positions``, ``quote_snapshot``,
    ``candles``) take an optional ``timeout`` defaulting to
    ``DEFAULT_READ_TIMEOUT_SECONDS``; hosts that need a tighter bound thread
    an explicit value through the adapter instead. A hung state-changing submission never blocks a
    reconciliation or read-only observation behind it.
    """

    def health(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> bool: ...

    def submit(self, request: DhanOrderRequest, *, timeout: float) -> DhanOrderResponse: ...

    def cancel(self, correlation_id: str, *, timeout: float) -> DhanOrderResponse: ...

    def reconcile(self, correlation_id: str, *, timeout: float) -> DhanOrderDetail: ...

    def fund_limits(
        self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    ) -> DhanFundsSnapshot: ...

    def positions(
        self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    ) -> DhanPositionsSnapshot: ...

    def quote_snapshot(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> DhanQuoteSnapshot | None: ...

    def candles(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        instrument_type: str = "EQUITY",
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> tuple[DhanCandleSnapshot, ...]: ...

    def close(self) -> None: ...


class _DhanClient(Protocol):
    def get_fund_limits(self) -> object: ...

    def get_positions(self) -> object: ...

    def place_order(self, **kwargs: object) -> object: ...

    def cancel_order(self, order_id: str) -> object: ...

    def get_order_by_correlationID(self, correlation_id: str) -> object: ...


@dataclass(slots=True)
class DhanSDKTransport:
    """Official DhanHQ SDK wrapper; vendor types never leave this class.

    Timeout enforcement runs each blocking SDK call on a worker thread. Three
    lanes exist: state-changing submissions (``submit`` and the vendor cancel
    inside ``cancel``) share one single-worker lane and stay serialized, so a
    second submission can never overtake or run concurrently with an
    in-flight one. Reconciliation runs on its own dedicated lane, so a
    saturated read lane can never starve the recovery read that must follow
    an uncertain submission. The remaining read-only observations (``health``,
    ``fund_limits``, ``positions``, ``quote_snapshot``, ``candles``) share a
    query lane. The timeout bounds the
    caller's wait; a slow SDK call may still complete in the background after
    the timeout, in which case its late result is discarded and the caller
    observes UNKNOWN/reconciliation-required (never a locally invented
    REJECTED, retry, or resubmission).
    """

    credentials: DhanCredentials
    _client: _DhanClient = field(init=False, repr=False)
    _context: object = field(init=False, repr=False)
    _submit_executor: ThreadPoolExecutor = field(init=False, repr=False)
    _reconcile_executor: ThreadPoolExecutor = field(init=False, repr=False)
    _query_executor: ThreadPoolExecutor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            from dhanhq import DhanContext, dhanhq  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("dhanhq SDK is not installed") from exc

        context = DhanContext(
            self.credentials.client_id,
            self.credentials.access_token,
        )
        self._context = context
        self._client = dhanhq(context)
        self._submit_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dhan-sdk")
        self._reconcile_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="dhan-reconcile"
        )
        self._query_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dhan-query")

    def _call_with_timeout(
        self,
        func: Callable[..., object],
        *args: object,
        timeout: float,
        operation: str,
        executor: ThreadPoolExecutor,
        **kwargs: object,
    ) -> object:
        future: Future[object] = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except TimeoutError as exc:
            future.cancel()
            raise DhanTimeoutError(operation, timeout) from exc

    def health(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> bool:
        try:
            response = self._call_with_timeout(
                self._client.get_fund_limits,
                timeout=timeout,
                operation="health",
                executor=self._query_executor,
            )
        except Exception:
            return False
        status, _, _ = _envelope(response)
        return status == "success"

    def submit(self, request: DhanOrderRequest, *, timeout: float) -> DhanOrderResponse:
        response = self._call_with_timeout(
            self._client.place_order,
            security_id=request.security_id,
            exchange_segment=request.exchange_segment,
            transaction_type=request.transaction_type,
            quantity=request.quantity,
            order_type=request.order_type,
            product_type=request.product_type,
            price=float(request.price),
            trigger_price=float(request.trigger_price),
            validity=request.validity,
            tag=request.correlation_id,
            timeout=timeout,
            operation="submit",
            executor=self._submit_executor,
        )
        return _order_response(response)

    def cancel(self, correlation_id: str, *, timeout: float) -> DhanOrderResponse:
        """Cancel bounded by up to two sequential timeout windows.

        ``cancel`` first reconciles (one ``timeout`` window) and then issues
        the vendor cancel (a second ``timeout`` window), so the worst-case
        broker interaction is approximately ``2 * timeout``.
        """
        detail = self.reconcile(correlation_id, timeout=timeout)
        if detail.order_id is None:
            return DhanOrderResponse(
                order_id=None,
                order_status="UNKNOWN",
                observed_at=datetime.now(UTC),
                message="Dhan order could not be resolved by correlation id",
            )
        response = self._call_with_timeout(
            self._client.cancel_order,
            detail.order_id,
            timeout=timeout,
            operation="cancel",
            executor=self._submit_executor,
        )
        return _order_response(response)

    def reconcile(self, correlation_id: str, *, timeout: float) -> DhanOrderDetail:
        response = self._call_with_timeout(
            self._client.get_order_by_correlationID,
            correlation_id,
            timeout=timeout,
            operation="reconcile",
            executor=self._reconcile_executor,
        )
        return _order_detail(response)

    def fund_limits(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanFundsSnapshot:
        try:
            response = self._call_with_timeout(
                self._client.get_fund_limits,
                timeout=timeout,
                operation="fund_limits",
                executor=self._query_executor,
            )
        except Exception as exc:
            return DhanFundsSnapshot(
                observed_at=datetime.now(UTC),
                available=False,
                message=f"Dhan fund-limits transport failure: {exc}",
            )
        return _funds_snapshot(response)

    def positions(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanPositionsSnapshot:
        try:
            response = self._call_with_timeout(
                self._client.get_positions,
                timeout=timeout,
                operation="positions",
                executor=self._query_executor,
            )
        except Exception as exc:
            return DhanPositionsSnapshot(
                observed_at=datetime.now(UTC),
                available=False,
                message=f"Dhan positions transport failure: {exc}",
            )
        return _positions_snapshot(response)

    def quote_snapshot(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> DhanQuoteSnapshot | None:
        """Re-observe one quote packet; transport failure means unavailable."""
        try:
            from dhanhq._market_feed import MarketFeed  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover - optional dependency
            return None

        try:
            response = self._call_with_timeout(
                MarketFeed(self._context).quote_data,
                {exchange_segment: [security_id]},
                timeout=timeout,
                operation="quote_snapshot",
                executor=self._query_executor,
            )
        except Exception:
            return None
        return _quote_snapshot(response, security_id, exchange_segment)

    def candles(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        instrument_type: str = "EQUITY",
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> tuple[DhanCandleSnapshot, ...]:
        """Fetch normalized historical candles for one Dhan instrument."""
        try:
            from dhanhq import HistoricalData
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("dhanhq SDK is not installed") from exc

        history = HistoricalData(self._context)
        from_date = start.strftime("%Y-%m-%d")
        to_date = end.strftime("%Y-%m-%d")
        if timeframe == "1d":
            response = self._call_with_timeout(
                history.historical_daily_data,
                security_id,
                exchange_segment,
                instrument_type,
                from_date,
                to_date,
                timeout=timeout,
                operation="candles",
                executor=self._query_executor,
            )
        else:
            interval = _intraday_interval(timeframe)
            response = self._call_with_timeout(
                history.intraday_minute_data,
                security_id,
                exchange_segment,
                instrument_type,
                from_date,
                to_date,
                interval=interval,
                timeout=timeout,
                operation="candles",
                executor=self._query_executor,
            )
        return _candle_snapshots(response, timeframe=timeframe)

    def close(self) -> None:
        """Shut down the internal executors deterministically.

        Explicit lifecycle ownership lives with the host
        (``DhanHostRuntime.close`` calls this); ``__del__`` is only a
        best-effort fallback and never blocks.
        """
        for name in ("_submit_executor", "_reconcile_executor", "_query_executor"):
            executor = getattr(self, name, None)
            if executor is None:
                continue
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            except RuntimeError:
                pass

    def __del__(self) -> None:  # pragma: no cover - defensive fallback only
        try:
            for name in ("_submit_executor", "_reconcile_executor", "_query_executor"):
                executor = getattr(self, name, None)
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


@dataclass(slots=True)
class InMemoryDhanTransport:
    """Deterministic transport used by QuantX tests; never touches the network."""

    response_status: str = "PENDING"
    order_id: str = "dhan-test-order"
    filled_quantity: Decimal = Decimal("0")
    average_traded_price: Decimal | None = None
    funds_available: bool = True
    funds_available_balance: Decimal | None = Decimal("5000")
    funds_utilized_amount: Decimal | None = Decimal("1200")
    funds_message: str = ""
    positions_available: bool = True
    position_snapshots: tuple[DhanPositionSnapshot, ...] = ()
    positions_message: str = ""
    quote_snapshots: dict[tuple[str, str], DhanQuoteSnapshot] = field(default_factory=dict)
    candle_snapshots: dict[tuple[str, str], tuple[DhanCandleSnapshot, ...]] = field(
        default_factory=dict
    )
    _submitted: list[DhanOrderRequest] = field(init=False, default_factory=list)
    _cancelled: list[str] = field(init=False, default_factory=list)

    @property
    def submitted(self) -> tuple[DhanOrderRequest, ...]:
        return tuple(self._submitted)

    @property
    def cancelled(self) -> tuple[str, ...]:
        return tuple(self._cancelled)

    def health(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> bool:
        return True

    def close(self) -> None:
        """No-op lifecycle hook so the host can close any transport uniformly."""

    def submit(self, request: DhanOrderRequest, *, timeout: float) -> DhanOrderResponse:
        self._submitted.append(request)
        return DhanOrderResponse(
            order_id=self.order_id,
            order_status=self.response_status,
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def cancel(self, correlation_id: str, *, timeout: float) -> DhanOrderResponse:
        self._cancelled.append(correlation_id)
        return DhanOrderResponse(
            order_id=self.order_id,
            order_status="CANCELLED",
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def reconcile(self, correlation_id: str, *, timeout: float) -> DhanOrderDetail:
        return DhanOrderDetail(
            order_id=self.order_id,
            correlation_id=correlation_id,
            order_status=self.response_status,
            average_traded_price=self.average_traded_price,
            filled_quantity=self.filled_quantity,
            exchange_time="2026-01-01 10:00:00",
            update_time="2026-01-01 10:00:00",
        )

    def fund_limits(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanFundsSnapshot:
        return DhanFundsSnapshot(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            available_balance=self.funds_available_balance,
            utilized_amount=self.funds_utilized_amount,
            available=self.funds_available,
            message=self.funds_message,
        )

    def positions(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanPositionsSnapshot:
        return DhanPositionsSnapshot(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            positions=self.position_snapshots,
            available=self.positions_available,
            message=self.positions_message,
        )

    def quote_snapshot(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> DhanQuoteSnapshot | None:
        return self.quote_snapshots.get((security_id, exchange_segment))

    def candles(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        instrument_type: str = "EQUITY",
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> tuple[DhanCandleSnapshot, ...]:
        return tuple(
            snapshot
            for snapshot in self.candle_snapshots.get((security_id, exchange_segment), ())
            if snapshot.timeframe == timeframe and start <= snapshot.timestamp <= end
        )


def _order_response(response: object) -> DhanOrderResponse:
    envelope_status, remarks, payload = _envelope(response)
    if envelope_status != "success":
        return DhanOrderResponse(
            order_id=None,
            order_status="UNKNOWN",
            observed_at=datetime.now(UTC),
            message=remarks,
            raw={"status": envelope_status, "remarks": remarks, "data": payload},
        )
    status = str(payload.get("orderStatus", "UNKNOWN"))
    order_id = payload.get("orderId")
    return DhanOrderResponse(
        order_id=str(order_id) if order_id is not None else None,
        order_status=status,
        observed_at=datetime.now(UTC),
        message=str(payload.get("message", "")),
        raw={"status": envelope_status, "remarks": remarks, "data": payload},
    )


def _order_detail(response: object) -> DhanOrderDetail:
    status, remarks, payload = _envelope(response)
    if status != "success":
        return DhanOrderDetail(
            order_id=None,
            correlation_id=None,
            order_status="UNKNOWN",
            average_traded_price=None,
            filled_quantity=Decimal("0"),
            exchange_time=None,
            update_time=None,
            message=remarks,
            raw={"status": status, "remarks": remarks, "data": payload},
        )
    order_id = payload.get("orderId")
    correlation_id = payload.get("correlationId")
    return DhanOrderDetail(
        order_id=str(order_id) if order_id is not None else None,
        correlation_id=(str(correlation_id) if correlation_id is not None else None),
        order_status=str(payload.get("orderStatus", "UNKNOWN")),
        average_traded_price=decimal_field(payload, "averageTradedPrice"),
        filled_quantity=extract_filled_quantity(payload),
        exchange_time=(str(payload["exchangeTime"]) if payload.get("exchangeTime") else None),
        update_time=(str(payload["updateTime"]) if payload.get("updateTime") else None),
        message=str(payload.get("omsErrorDescription", "")),
        raw={"status": status, "remarks": remarks, "data": payload},
    )


def _envelope(response: object) -> tuple[str, str, DhanPayload]:
    if not isinstance(response, dict):
        raise TypeError("Dhan SDK response must be a mapping")
    status = str(response.get("status", "failure"))
    remarks = str(response.get("remarks", ""))
    data = response.get("data")
    if not isinstance(data, dict):
        data = {}
    return status, remarks, data


def _money_field(payload: DhanPayload, key: str) -> Decimal | None:
    """Parse an optional broker money field; missing stays missing, never zero."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid Dhan decimal field: {key}") from exc


def _funds_snapshot(response: object) -> DhanFundsSnapshot:
    """Normalize a fund-limits envelope; unusable data stays unavailable."""
    try:
        envelope_status, remarks, payload = _envelope(response)
    except (TypeError, ValueError) as exc:
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=f"unrecognized Dhan fund-limits response: {exc}",
        )
    if envelope_status != "success":
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=remarks or "Dhan fund limits reported failure",
        )
    try:
        available_balance = _money_field(payload, "availabelBalance")
        if available_balance is None:
            available_balance = _money_field(payload, "availableBalance")
        utilized_amount = _money_field(payload, "utilizedAmount")
    except ValueError as exc:
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=str(exc),
        )
    if available_balance is None and utilized_amount is None:
        return DhanFundsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message="Dhan fund limits carry no usable balance fields",
        )
    return DhanFundsSnapshot(
        observed_at=datetime.now(UTC),
        available_balance=available_balance,
        utilized_amount=utilized_amount,
        available=True,
        message=remarks,
    )


def _positions_snapshot(response: object) -> DhanPositionsSnapshot:
    """Normalize a positions envelope; malformed data stays unavailable."""
    if not isinstance(response, dict):
        return DhanPositionsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message="Dhan positions response must be a mapping",
        )
    envelope_status = str(response.get("status", "failure"))
    remarks = str(response.get("remarks", ""))
    if envelope_status != "success":
        return DhanPositionsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message=remarks or "Dhan positions reported failure",
        )
    entries = response.get("data")
    if not isinstance(entries, list):
        return DhanPositionsSnapshot(
            observed_at=datetime.now(UTC),
            available=False,
            message="Dhan positions data must be a list",
        )
    positions: list[DhanPositionSnapshot] = []
    for entry in entries:
        position = _position_snapshot(entry)
        if position is None:
            return DhanPositionsSnapshot(
                observed_at=datetime.now(UTC),
                available=False,
                message="Dhan position entry is malformed",
            )
        positions.append(position)
    return DhanPositionsSnapshot(
        observed_at=datetime.now(UTC),
        positions=tuple(positions),
        available=True,
        message=remarks,
    )


_INTRADAY_INTERVALS = {"1m": 1, "5m": 5, "15m": 15, "25m": 25, "60m": 60}


def _intraday_interval(timeframe: str) -> int:
    """Map a minute timeframe onto the Dhan intraday interval parameter."""
    try:
        return _INTRADAY_INTERVALS[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported Dhan intraday timeframe: {timeframe}") from exc


def _quote_snapshot(
    response: object,
    security_id: str,
    exchange_segment: str,
) -> DhanQuoteSnapshot | None:
    """Normalize one Dhan quote packet; absent data stays unavailable.

    Malformed numeric content raises rather than inventing prices. Timestamp
    falls back to the snapshot time only when the packet carries no parsable
    trade time.
    """
    try:
        envelope_status, _, payload = _envelope(response)
    except (TypeError, ValueError):
        return None
    if envelope_status != "success":
        return None
    segment = payload.get(exchange_segment)
    if not isinstance(segment, dict):
        return None
    packet = segment.get(security_id)
    if not isinstance(packet, dict):
        return None
    last_price = _money_field(packet, "last_price")
    bid_price, bid_size = _depth_level(packet, "buy")
    ask_price, ask_size = _depth_level(packet, "sell")
    observed_at = parse_dhan_timestamp(packet.get("last_trade_time"))
    return DhanQuoteSnapshot(
        security_id=security_id,
        exchange_segment=exchange_segment,
        observed_at=observed_at or datetime.now(UTC),
        last_price=last_price,
        bid_price=bid_price,
        ask_price=ask_price,
        bid_size=bid_size,
        ask_size=ask_size,
    )


def _depth_level(packet: DhanPayload, side: str) -> tuple[Decimal | None, Decimal | None]:
    """Read the best depth level; missing depth stays missing, never zero."""
    depth = packet.get("depth")
    if not isinstance(depth, dict):
        return None, None
    levels = depth.get("buy" if side == "buy" else "sell")
    if not isinstance(levels, list) or not levels:
        return None, None
    best = levels[0]
    if not isinstance(best, dict):
        raise ValueError("Dhan market depth level is malformed")
    return _money_field(best, "price"), _money_field(best, "quantity")


def _candle_snapshots(
    response: object,
    *,
    timeframe: str,
) -> tuple[DhanCandleSnapshot, ...]:
    """Normalize Dhan chart arrays without lossy float conversions.

    The endpoint returns parallel arrays; unequal lengths or invalid entries
    raise rather than silently dropping or inventing candles. Exchange epoch
    timestamps are interpreted in Asia/Kolkata, consistent with
    ``parse_dhan_timestamp``.
    """
    envelope_status, remarks, payload = _envelope(response)
    if envelope_status != "success":
        raise ValueError(f"Dhan historical data reported failure: {remarks or 'unknown'}")
    series = payload.get("data", payload)
    if not isinstance(series, dict):
        raise ValueError("Dhan candle payload must be a mapping")
    columns = {}
    for key in ("open", "high", "low", "close", "volume", "start_Time"):
        values = series.get(key)
        if not isinstance(values, list):
            raise ValueError(f"Dhan candle series is missing {key!r}")
        columns[key] = values
    lengths = {len(values) for values in columns.values()}
    if len(lengths) != 1:
        raise ValueError("Dhan candle series lengths do not match")
    snapshots: list[DhanCandleSnapshot] = []
    for index in range(lengths.pop()):
        try:
            timestamp = _candle_timestamp(columns["start_Time"][index])
            candle = DhanCandleSnapshot(
                timeframe=timeframe,
                timestamp=timestamp,
                open=_strict_decimal(columns["open"][index], "open"),
                high=_strict_decimal(columns["high"][index], "high"),
                low=_strict_decimal(columns["low"][index], "low"),
                close=_strict_decimal(columns["close"][index], "close"),
                volume=_strict_decimal(columns["volume"][index], "volume"),
            )
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"Dhan candle entry is malformed: {exc}") from exc
        snapshots.append(candle)
    return tuple(snapshots)


def _candle_timestamp(value: object) -> datetime:
    """Interpret a Dhan candle timestamp as a timezone-aware datetime."""
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.strip().lstrip("-").isdigit()
    ):
        return datetime.fromtimestamp(int(str(value).strip()), tz=ZoneInfo("Asia/Kolkata"))
    parsed = parse_dhan_timestamp(value if isinstance(value, str) else None)
    if parsed is None:
        raise ValueError(f"unrecognized Dhan candle timestamp: {value!r}")
    return parsed


def _strict_decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid Dhan decimal field: {field}") from exc


def _position_snapshot(entry: object) -> DhanPositionSnapshot | None:
    if not isinstance(entry, dict):
        return None
    security_id = entry.get("securityId")
    exchange_segment = entry.get("exchangeSegment")
    if security_id is None or not str(security_id).strip():
        return None
    if exchange_segment is None or not str(exchange_segment).strip():
        return None
    try:
        net_quantity = Decimal(str(entry.get("netQty")))
    except (InvalidOperation, ValueError, TypeError):
        return None
    try:
        average_price = _money_field(entry, "costPrice")
    except ValueError:
        return None
    return DhanPositionSnapshot(
        security_id=str(security_id),
        exchange_segment=str(exchange_segment),
        net_quantity=net_quantity,
        average_price=average_price,
    )
