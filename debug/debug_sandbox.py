import inspect
from datetime import datetime, timezone, timedelta
from t_tech.invest.grpc import Client
from app.config import TOKEN

FIGI = "BBG004730N88"  # SBER

with Client(token=TOKEN.strip()) as client:
    ins = client.instruments
    print("get_dividends sig:", inspect.signature(ins.get_dividends))

    req = type(inspect.signature(ins.get_dividends).parameters["request"].default)()
    # в разных версиях поля могут называться figi / instrument_id
    if hasattr(req, "figi"):
        req.figi = FIGI
    if hasattr(req, "instrument_id"):
        req.instrument_id = FIGI

    # from/to часто как datetime (обёртка), либо как Timestamp — зависит от версии
    dt_from = datetime.now(timezone.utc) - timedelta(days=365*5)
    dt_to = datetime.now(timezone.utc)

    if hasattr(req, "from_"):
        req.from_ = dt_from
    if hasattr(req, "to"):
        req.to = dt_to
    if hasattr(req, "from"):
        setattr(req, "from", dt_from)

    resp = ins.get_dividends(request=req)
    print(resp)