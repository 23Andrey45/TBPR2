from app.config import TOKEN
from t_tech.invest.grpc import Client
from t_tech.invest.grpc.common_pb2 import MoneyValue

token = TOKEN.strip()

with Client(token=token) as client:
    # 1) аккаунт
    resp = client.sandbox.get_sandbox_accounts()
    accounts = list(getattr(resp, "accounts", []) or [])
    if not accounts:
        opened = client.sandbox.open_sandbox_account()
        print("opened:", opened)
        resp = client.sandbox.get_sandbox_accounts()
        accounts = list(getattr(resp, "accounts", []) or [])

    acc_id = accounts[0].id
    print("using account:", acc_id)

    # 2) пополнение (проверь, что метод существует)
    print("has sandbox_pay_in:", hasattr(client.sandbox, "sandbox_pay_in"))

    client.sandbox.sandbox_pay_in(
        account_id=acc_id,
        amount=MoneyValue(currency="rub", units=100_000, nano=0),
    )
    print("paid in 100000 rub")

    # 3) баланс денег через get_positions()
    pos = client.operations.get_positions(account_id=acc_id)
    print("money:", list(getattr(pos, "money", []) or []))
    print("blocked_money:", list(getattr(pos, "blocked_money", []) or []))