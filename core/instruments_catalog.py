# core/instruments_catalog.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum

from t_tech.invest import Client

InstrumentStatus = None
try:
    from t_tech.invest.grpc.instruments_pb2 import InstrumentStatus as _InstrumentStatus  # type: ignore
    InstrumentStatus = _InstrumentStatus
except Exception:
    try:
        from t_tech.invest.grpc.common_pb2 import InstrumentStatus as _InstrumentStatus  # type: ignore
        InstrumentStatus = _InstrumentStatus
    except Exception:
        InstrumentStatus = None


class InstrumentKind(str, Enum):
    SHARE = "share"
    BOND = "bond"
    ETF = "etf"


@dataclass(frozen=True)
class InstrumentInfo:
    kind: str                 # "share" | "bond" | "etf"
    instrument_id: str        # то, что будем передавать в get_all_candles()
    ticker: str
    name: str
    isin: str
    figi: str
    uid: str

    def fav_key(self) -> str:
        # ключ избранного: тип + (isin или instrument_id)
        return f"{self.kind}:{self.isin or self.instrument_id}"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "InstrumentInfo":
        return InstrumentInfo(
            kind=d.get("kind", "") or "",
            instrument_id=d.get("instrument_id", "") or "",
            ticker=d.get("ticker", "") or "",
            name=d.get("name", "") or "",
            isin=d.get("isin", "") or "",
            figi=d.get("figi", "") or "",
            uid=d.get("uid", "") or "",
        )


def _pick_instrument_id(obj) -> str:
    # для свечей обычно подходит figi; если нет — uid
    figi = getattr(obj, "figi", "") or ""
    uid = getattr(obj, "uid", "") or ""
    return figi or uid


def _get_instruments_service(client: Client):
    for path in (
        ("instruments",),
        ("instruments_service",),
        ("services", "instruments"),
        ("services", "instruments_service"),
    ):
        try:
            obj = client
            for p in path:
                obj = getattr(obj, p)
            return obj
        except Exception:
            continue
    raise RuntimeError("Не найден сервис instruments у Client")


def _fetch_by_method(token: str, kind: InstrumentKind) -> list[InstrumentInfo]:
    """
    kind -> instruments.shares/bonds/etfs
    фильтруем по api_trade_available_flag (если поле есть)
    """
    method_name = {
        InstrumentKind.SHARE: "shares",
        InstrumentKind.BOND: "bonds",
        InstrumentKind.ETF: "etfs",
    }[kind]

    with Client(token) as client:
        svc = _get_instruments_service(client)
        if not hasattr(svc, method_name):
            raise RuntimeError(f"У instruments service нет метода {method_name}()")

        method = getattr(svc, method_name)

        resp = None
        if InstrumentStatus is not None:
            try:
                resp = method(instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE)
            except TypeError:
                resp = None

        if resp is None:
            resp = method()

        items = list(getattr(resp, "instruments", []) or [])

        out: list[InstrumentInfo] = []
        for x in items:
            # только доступные
            trade_ok = getattr(x, "api_trade_available_flag", None)
            if trade_ok is False:
                continue

            instrument_id = _pick_instrument_id(x)
            if not instrument_id:
                continue

            out.append(
                InstrumentInfo(
                    kind=str(kind.value),
                    instrument_id=instrument_id,
                    ticker=getattr(x, "ticker", "") or "",
                    name=getattr(x, "name", "") or "",
                    isin=getattr(x, "isin", "") or "",
                    figi=getattr(x, "figi", "") or "",
                    uid=getattr(x, "uid", "") or "",
                )
            )

        out.sort(key=lambda i: (i.ticker, i.name))
        return out


def fetch_available_shares(token: str) -> list[InstrumentInfo]:
    return _fetch_by_method(token, InstrumentKind.SHARE)


def fetch_available_bonds(token: str) -> list[InstrumentInfo]:
    return _fetch_by_method(token, InstrumentKind.BOND)


def fetch_available_etfs(token: str) -> list[InstrumentInfo]:
    return _fetch_by_method(token, InstrumentKind.ETF)


def _quotation_to_float(q) -> float:
    return float(getattr(q, "units", 0)) + float(getattr(q, "nano", 0)) / 1e9


def _extract_tick_from_obj(obj) -> float | None:
    # В разных версиях SDK шаг цены может лежать в похожих полях,
    # но берем только «ценовые» поля, чтобы не схватить шаг лота/другой параметр.
    candidates = [
        "min_price_increment",
        "price_step",
    ]
    vals: list[float] = []
    for name in candidates:
        if not hasattr(obj, name):
            continue
        raw = getattr(obj, name)
        if raw is None:
            continue
        if hasattr(raw, "units") and hasattr(raw, "nano"):
            v = _quotation_to_float(raw)
        else:
            try:
                v = float(raw)
            except Exception:
                continue
        if v > 0:
            vals.append(v)

    if not vals:
        return None

    # Берем минимальный положительный шаг.
    return min(vals)


def fetch_min_price_increment(token: str, *, figi: str = "", instrument_id: str = "") -> float | None:
    token = token.strip()
    figi = (figi or "").strip()
    instrument_id = (instrument_id or "").strip()

    with Client(token) as client:
        svc = _get_instruments_service(client)

        # Ищем в каталогах: для текущей версии это стабильнее, чем get_instrument_by,
        # который может требовать обязательный id_type.
        for name in ("shares", "bonds", "etfs"):
            method = getattr(svc, name, None)
            if method is None:
                continue
            try:
                resp = method()
                items = list(getattr(resp, "instruments", []) or [])
                for x in items:
                    xf = str(getattr(x, "figi", "") or "")
                    xid = str(getattr(x, "uid", "") or "")
                    if (figi and xf == figi) or (instrument_id and (xid == instrument_id or xf == instrument_id)):
                        tick = _extract_tick_from_obj(x)
                        if tick is not None:
                            return tick
            except Exception:
                continue

    return None