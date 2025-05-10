from typing import Dict, Optional, List, Union
from .models import User, Balance, MarketOrder, LimitOrder, OrderStatus
from uuid import UUID
from datetime import datetime

class Database:
    def __init__(self):
        self.users: Dict[str, User] = {}  # api_key -> User
        self.users_by_name: Dict[str, User] = {}  # name -> User
        self.balances: Dict[UUID, Balance] = {}  # user_id -> Balance
        self.market_orders: Dict[UUID, MarketOrder] = {}  # order_id -> MarketOrder
        self.limit_orders: Dict[UUID, LimitOrder] = {}  # order_id -> LimitOrder

    def add_user(self, user: User) -> None:
        self.users[user.api_key] = user
        self.users_by_name[user.name] = user

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        return self.users.get(api_key)

    def get_user_by_name(self, name: str) -> Optional[User]:
        return self.users_by_name.get(name)

    def get_balance(self, user_id: UUID) -> Balance:
        if user_id not in self.balances:
            self.balances[user_id] = Balance(user_id=user_id)
        return self.balances[user_id]

    def update_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        balance = self.get_balance(user_id)
        current_amount = balance.balances.get(ticker, 0)
        balance.balances[ticker] = current_amount + amount

    def add_market_order(self, order: MarketOrder) -> None:
        self.market_orders[order.id] = order

    def add_limit_order(self, order: LimitOrder) -> None:
        self.limit_orders[order.id] = order

    def get_order(self, order_id: UUID) -> Optional[Union[MarketOrder, LimitOrder]]:
        return self.market_orders.get(order_id) or self.limit_orders.get(order_id)

    def get_user_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        market_orders = [order for order in self.market_orders.values() if order.user_id == user_id]
        limit_orders = [order for order in self.limit_orders.values() if order.user_id == user_id]
        return market_orders + limit_orders

    def get_active_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        return [
            order for order in self.get_user_orders(user_id)
            if order.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
        ]

# Create a global database instance
db = Database() 