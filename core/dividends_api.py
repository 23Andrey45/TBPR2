# core/dividends_api.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import inspect

from t_tech.invest.grpc import Client


def money_to_float(m) -> float:
    return float(getattr(m, "units", 0)) + float(getattr(m, "nano", 0)) / 1e9


def quotation_to_float(q) -> float:
    return float(getattr(q, "units", 0)) + float(getattr(q, "nano", 0)) / 1e9


@dataclass(frozen=True)
class DividendEvent:
    last_buy_date: datetime
    record_date: datetime
    declared_date: datetime
    payment_date: datetime

    dividend_net_per_share: float
    currency: str

    close_price: float
    yield_value: float


def fetch_dividends(token: str, *, figi: str, from_: datetime, to: datetime) -> list[DividendEvent]:
    token = token.strip()
    figi = (figi or "").strip()
    if not figi:
        return []

    with Client(token=token) as client:
        ins = client.instruments
        method = ins.get_dividends

        sig = inspect.signature(method)
        req = type(sig.parameters["request"].default)()

        if hasattr(req, "figi"):
            req.figi = figi
        if hasattr(req, "from_"):
            req.from_ = from_
        if hasattr(req, "to"):
            req.to = to

        resp = method(request=req)
        divs = list(getattr(resp, "dividends", []) or [])

        out: list[DividendEvent] = []
        for d in divs:
            mv = getattr(d, "dividend_net", None)
            if mv is None:
                continue

            close_mv = getattr(d, "close_price", None)
            yq = getattr(d, "yield_value", None)

            out.append(
                DividendEvent(
                    last_buy_date=getattr(d, "last_buy_date"),
                    record_date=getattr(d, "record_date"),
                    declared_date=getattr(d, "declared_date"),
                    payment_date=getattr(d, "payment_date"),
                    dividend_net_per_share=money_to_float(mv),
                    currency=str(getattr(mv, "currency", "")),
                    close_price=money_to_float(close_mv) if close_mv is not None else 0.0,
                    yield_value=quotation_to_float(yq) if yq is not None else 0.0,
                )
            )
        return out
