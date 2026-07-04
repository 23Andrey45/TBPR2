# tinvest_client.py
from t_tech.invest import Client
from app.config import TOKEN


class TInvestGateway:
    def __init__(self):
        self.token = TOKEN
        if not self.token:
            raise ValueError("Token is empty")

    def portfolio(self, account_id: str):
        with Client(self.token) as client:
            return client.operations.get_portfolio(account_id=account_id)

    def last_price(self, figi: str):
        with Client(self.token) as client:
            response = client.market_data.get_last_prices(figi=[figi])
            return response.last_prices[0]