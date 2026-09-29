"""Session-aware execution guard."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.deployment import ExecutionMode
from quantx.domain.sessions import TradingSession


@dataclass(frozen=True, slots=True)
class SessionGuardResult:
    allowed: bool
    reason: str = ""


class SessionExecutionGuard:
    """Block execution outside the declared trading session.

    Replay remains exempt because replay intentionally controls its own
    historical timeline. All other execution modes are session-aware.
    """

    def __init__(self, session: TradingSession) -> None:
        self._session = session

    def check(self, mode: ExecutionMode) -> SessionGuardResult:
        if mode is ExecutionMode.REPLAY:
            return SessionGuardResult(True)
        status = self._session.status()
        if not status.open:
            return SessionGuardResult(
                False,
                f"trading session is closed ({status.timezone})",
            )
        return SessionGuardResult(True)
