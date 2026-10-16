"""Strict read-only typed projection over canonical StrategyIR parameter strings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .ir import StrategyIR

_INTEGER = re.compile(r"(?:0|[1-9][0-9]*|-[1-9][0-9]*)")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_MISSING = object()


@dataclass(frozen=True, slots=True)
class TypedParams:
    """Typed accessors that never rewrite or normalize StrategyIR strings."""

    parameters: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, tuple):
            raise TypeError("TypedParams parameters must be the canonical tuple")
        keys = tuple(key for key, _ in self.parameters)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("TypedParams requires sorted, unique StrategyIR parameters")

    @classmethod
    def from_ir(cls, ir: StrategyIR) -> TypedParams:
        return cls(ir.parameters)

    def _raw(self, name: str, default: object = _MISSING) -> str | object:
        if not name.strip():
            raise ValueError("parameter field name must not be empty")
        for key, value in self.parameters:
            if key == name:
                return value
        if default is _MISSING:
            raise ValueError(f"{name}: required parameter is missing")
        return default

    def get_string(self, name: str, *, default: object = _MISSING) -> str:
        value = self._raw(name, default)
        if not isinstance(value, str):
            raise ValueError(f"{name}: default must be a string")
        return value

    def get_bool(self, name: str, *, default: object = _MISSING) -> bool:
        value = self._raw(name, default)
        if type(value) is bool:
            return value
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError(f"{name}: expected exactly 'true' or 'false'")

    def get_int(
        self,
        name: str,
        *,
        default: object = _MISSING,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        value = self._raw(name, default)
        if type(value) is int:
            parsed = value
        elif isinstance(value, str) and _INTEGER.fullmatch(value):
            parsed = int(value)
        else:
            raise ValueError(f"{name}: invalid integer lexical form")
        if minimum is not None and parsed < minimum:
            raise ValueError(f"{name}: must be at least {minimum}")
        if maximum is not None and parsed > maximum:
            raise ValueError(f"{name}: must be at most {maximum}")
        return parsed

    def get_decimal(
        self,
        name: str,
        *,
        default: object = _MISSING,
        minimum: Decimal | None = None,
        maximum: Decimal | None = None,
    ) -> Decimal:
        value = self._raw(name, default)
        if isinstance(value, Decimal):
            parsed = value
            spelling = str(value)
        elif isinstance(value, str) and _DECIMAL.fullmatch(value):
            spelling = value
            try:
                parsed = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError(f"{name}: invalid Decimal lexical form") from exc
        else:
            raise ValueError(f"{name}: invalid Decimal lexical form")
        if spelling.startswith("-") and parsed.is_zero():
            raise ValueError(f"{name}: negative zero is noncanonical")
        if not parsed.is_finite():
            raise ValueError(f"{name}: Decimal must be finite")
        if minimum is not None and parsed < minimum:
            raise ValueError(f"{name}: must be at least {minimum}")
        if maximum is not None and parsed > maximum:
            raise ValueError(f"{name}: must be at most {maximum}")
        return parsed
