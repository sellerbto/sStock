import pytest
from datetime import datetime, UTC
from uuid import UUID, uuid4
from api.database import Database
from api.models import (
    User, UserRole, Direction, OrderStatus,
    MarketOrderBody, LimitOrderBody, MarketOrder, LimitOrder,
    ExecutionDetails, OrderExecutionSummary
)

@pytest.fixture
def db():
    """Фикстура для создания тестовой базы данных"""
    return Database()

@pytest.fixture
def user(db):
    """Фикстура для создания тестового пользователя"""
    user = User.create(name="test_user", password="test_password")
    db.add_user(user)
    return user

def test_add_and_get_user(db, user):
    """Тест добавления и получения пользователя"""
    # Проверяем получение по api_key
    retrieved_user = db.get_user_by_api_key(user.api_key)
    assert retrieved_user == user
    
    # Проверяем получение по имени
    retrieved_user = db.get_user_by_name(user.name)
    assert retrieved_user == user

def test_balance_operations(db, user):
    """Тест операций с балансом"""
    # Проверяем начальный баланс
    balance = db.get_balance(user.id)
    assert balance.balances == {}
    
    # Добавляем средства
    db.update_balance(user.id, "BTC", 100)
    balance = db.get_balance(user.id)
    assert balance.balances["BTC"] == 100
    
    # Списываем средства
    db.update_balance(user.id, "BTC", -50)
    balance = db.get_balance(user.id)
    assert balance.balances["BTC"] == 50

def test_market_order_execution(db, user):
    """Тест исполнения рыночной заявки"""
    # Создаем лимитную заявку на продажу
    limit_order = LimitOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=user.id,
        timestamp=datetime.now(UTC),
        body=LimitOrderBody(
            direction=Direction.SELL,
            ticker="BTC",
            qty=10,
            price=1000
        )
    )
    db.add_limit_order(limit_order)
    
    # Создаем рыночную заявку на покупку
    market_order = MarketOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=user.id,
        timestamp=datetime.now(UTC),
        body=MarketOrderBody(
            direction=Direction.BUY,
            ticker="BTC",
            qty=5
        )
    )
    db.add_market_order(market_order)
    
    # Исполняем рыночную заявку
    db.execute_market_order(market_order)
    
    # Проверяем статус заявок
    assert market_order.status == OrderStatus.EXECUTED
    assert limit_order.status == OrderStatus.PARTIALLY_EXECUTED
    
    # Проверяем детали исполнения
    executions = db.get_order_executions(market_order.id)
    assert len(executions) == 1
    execution = executions[0]
    assert execution.quantity == 5
    assert execution.price == 1000
    assert execution.counterparty_order_id == limit_order.id

def test_order_execution_summary(db, user):
    """Тест сводки исполнения заявки"""
    # Создаем и исполняем заявку
    order = MarketOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=user.id,
        timestamp=datetime.now(UTC),
        body=MarketOrderBody(
            direction=Direction.BUY,
            ticker="BTC",
            qty=10
        )
    )
    db.add_market_order(order)
    
    # Добавляем несколько исполнений
    execution1 = ExecutionDetails(
        execution_id=uuid4(),
        timestamp=datetime.now(UTC),
        quantity=4,
        price=1000,
        counterparty_order_id=uuid4()
    )
    execution2 = ExecutionDetails(
        execution_id=uuid4(),
        timestamp=datetime.now(UTC),
        quantity=6,
        price=1100,
        counterparty_order_id=uuid4()
    )
    
    db._add_execution(order.id, execution1)
    db._add_execution(order.id, execution2)
    
    # Обновляем статус и сводку
    db._update_order_status_and_summary(order)
    
    # Проверяем сводку
    summary = db.get_order_execution_summary(order.id)
    assert summary is not None
    assert summary.total_filled == 10
    assert summary.average_price == 1060.0  # (4*1000 + 6*1100) / 10
    assert len(summary.executions) == 2

def test_get_user_orders(db, user):
    """Тест получения заявок пользователя"""
    # Создаем несколько заявок
    market_order = MarketOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=user.id,
        timestamp=datetime.now(UTC),
        body=MarketOrderBody(
            direction=Direction.BUY,
            ticker="BTC",
            qty=10
        )
    )
    limit_order = LimitOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=user.id,
        timestamp=datetime.now(UTC),
        body=LimitOrderBody(
            direction=Direction.SELL,
            ticker="ETH",
            qty=5,
            price=2000
        )
    )
    
    db.add_market_order(market_order)
    db.add_limit_order(limit_order)
    
    # Получаем все заявки пользователя
    orders = db.get_user_orders(user.id)
    assert len(orders) == 2
    assert market_order in orders
    assert limit_order in orders
    
    # Получаем активные заявки
    active_orders = db.get_active_orders(user.id)
    assert len(active_orders) == 2
    assert market_order in active_orders
    assert limit_order in active_orders 