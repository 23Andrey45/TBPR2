# core/strategies/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Any, Optional


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    type: str               # "int" | "float" | "str" | "bool" | "choice"
    default: Any
    description: str = ""
    choices: Optional[list[Any]] = None
    min: Optional[float] = None
    max: Optional[float] = None

    def parse(self, value: Any) -> Any:
        if value is None or value == "":
            value = self.default

        t = self.type.lower()

        if t == "str":
            return str(value)

        if t == "int":
            if isinstance(value, int):
                return value
            return int(str(value).strip())

        if t == "float":
            if isinstance(value, (int, float)):
                return float(value)
            s = str(value).strip().replace(",", ".")
            return float(s)

        if t == "bool":
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ("1", "true", "yes", "y", "да"):
                return True
            if s in ("0", "false", "no", "n", "нет"):
                return False
            return bool(value)

        if t == "choice":
            if self.choices is None:
                raise ValueError(f"ParamSpec.choice без choices: {self.key}")
            if value not in self.choices:
                raise ValueError(f"Недопустимое значение '{value}' для {self.key}. Допустимо: {self.choices}")
            return value

        raise ValueError(f"Неизвестный тип параметра: {self.type}")


@dataclass(frozen=True)
class StrategyContext:
    instrument: Any | None = None          # InstrumentInfo
    dividends: list[Any] = field(default_factory=list)  # list[DividendEvent]


@dataclass(frozen=True)
class StrategyResult:
    strategy_id: str
    strategy_name: str
    params_used: dict[str, Any]
    metrics: dict[str, str]
    extra: dict[str, Any] = field(default_factory=dict)


class Strategy(ABC):
    @property
    @abstractmethod
    def strategy_id(self) -> str: ...

    @property
    @abstractmethod
    def strategy_name(self) -> str: ...

    @abstractmethod
    def param_specs(self) -> list[ParamSpec]: ...

    def default_params(self) -> dict[str, Any]:
        return {p.key: p.default for p in self.param_specs()}

    def normalize_params(self, user_params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        user_params = user_params or {}
        out: dict[str, Any] = {}

        for p in self.param_specs():
            raw = user_params.get(p.key, p.default)
            val = p.parse(raw)

            if p.type.lower() in ("int", "float"):
                fv = float(val)
                if p.min is not None and fv < p.min:
                    raise ValueError(f"{p.key} < min ({fv} < {p.min})")
                if p.max is not None and fv > p.max:
                    raise ValueError(f"{p.key} > max ({fv} > {p.max})")

            out[p.key] = val

        return out

    @abstractmethod
    def run(self, candles, params: dict[str, Any], context: StrategyContext) -> StrategyResult: ...
