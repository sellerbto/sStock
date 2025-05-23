from typing import Dict, Optional, List, Union, Tuple
from .models import User, Balance, MarketOrder, LimitOrder, OrderStatus, Direction
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

    def get_best_price(self, ticker: str, direction: Direction) -> Optional[int]:
        """Получить лучшую цену для заданного направления"""
        orders = [
            order for order in self.limit_orders.values()
            if order.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
            and order.body.ticker == ticker
            and order.body.direction != direction  # Ищем встречные заявки
        ]
        
        if not orders:
            return None
            
        if direction == Direction.BUY:
            # Для покупки ищем самую низкую цену продажи
            return min(order.body.price for order in orders)
        else:
            # Для продажи ищем самую высокую цену покупки
            return max(order.body.price for order in orders)

    def execute_market_order(self, order: MarketOrder) -> None:
        """Исполнить рыночную заявку"""
        remaining_qty = order.body.qty
        ticker = order.body.ticker
        
        # Получаем все активные лимитные заявки для этого тикера
        limit_orders = [
            limit_order for limit_order in self.limit_orders.values()
            if limit_order.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
            and limit_order.body.ticker == ticker
            and limit_order.body.direction != order.body.direction
        ]
        
        # Сортируем заявки по цене
        if order.body.direction == Direction.BUY:
            # Для покупки сортируем по возрастанию цены
            limit_orders.sort(key=lambda x: x.body.price)
        else:
            # Для продажи сортируем по убыванию цены
            limit_orders.sort(key=lambda x: x.body.price, reverse=True)
        
        for limit_order in limit_orders:
            if remaining_qty == 0:
                break
                
            available_qty = limit_order.body.qty - limit_order.filled
            execute_qty = min(remaining_qty, available_qty)
            
            # Исполняем часть заявки
            self._execute_orders(order, limit_order, execute_qty)
            
            remaining_qty -= execute_qty
        
        # Обновляем статус рыночной заявки
        if remaining_qty == 0:
            order.status = OrderStatus.EXECUTED
        elif remaining_qty < order.body.qty:
            order.status = OrderStatus.PARTIALLY_EXECUTED
        
    def _execute_orders(self, order1: Union[MarketOrder, LimitOrder], order2: LimitOrder, qty: int) -> None:
        """Исполнить заявки между собой"""
        price = order2.body.price  # Используем цену лимитной заявки
        
        # Определяем покупателя и продавца
        if order1.body.direction == Direction.BUY:
            buyer, seller = order1, order2
        else:
            buyer, seller = order2, order1
            
        # Обновляем балансы
        self._update_balances(
            buyer.user_id, seller.user_id,
            buyer.body.ticker, qty, price
        )
        
        # Обновляем статус лимитной заявки
        if isinstance(order2, LimitOrder):
            order2.filled += qty
            if order2.filled == order2.body.qty:
                order2.status = OrderStatus.EXECUTED
            else:
                order2.status = OrderStatus.PARTIALLY_EXECUTED

    def _update_balances(self, buyer_id: UUID, seller_id: UUID, ticker: str, qty: int, price: int) -> None:
        """Обновить балансы после исполнения заявки"""
        # Списываем деньги у покупателя
        buyer_balance = self.get_balance(buyer_id)
        self.update_balance(buyer_id, "USD", -qty * price)  # Предполагаем, что базовая валюта USD
        self.update_balance(buyer_id, ticker, qty)
        
        # Начисляем деньги продавцу
        seller_balance = self.get_balance(seller_id)
        self.update_balance(seller_id, "USD", qty * price)
        self.update_balance(seller_id, ticker, -qty)

# Create a global database instance
db = Database() 