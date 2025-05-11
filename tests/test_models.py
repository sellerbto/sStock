import pytest
from datetime import datetime, UTC
from uuid import UUID, uuid4
from api.models import (
    User, UserRole, NewUser, Direction, OrderStatus,
    MarketOrderBody, LimitOrderBody, MarketOrder, LimitOrder,
    ExecutionDetails, OrderExecutionSummary
)

def test_user_creation():
    """Тест создания пользователя"""
    user = User.create(name="test_user", password="test_password")
    assert user.name == "test_user"
    assert user.role == UserRole.USER
    assert user.api_key.startswith("key-")
    assert user.check_password("test_password")
    assert not user.check_password("wrong_password")

def test_market_order_creation():
    """Тест создания рыночной заявки"""
    timestamp = datetime.now(UTC)
    order = MarketOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=uuid4(),
        timestamp=timestamp,
        body=MarketOrderBody(
            direction=Direction.BUY,
            ticker="BTC",
            qty=10
        )
    )
    assert order.id is not None
    assert order.status == OrderStatus.NEW
    assert order.timestamp == timestamp
    assert order.body.direction == Direction.BUY
    assert order.body.ticker == "BTC"
    assert order.body.qty == 10

def test_limit_order_creation():
    """Тест создания лимитной заявки"""
    timestamp = datetime.now(UTC)
    order = LimitOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=uuid4(),
        timestamp=timestamp,
        body=LimitOrderBody(
            direction=Direction.SELL,
            ticker="BTC",
            qty=5,
            price=1000
        )
    )
    assert order.id is not None
    assert order.status == OrderStatus.NEW
    assert order.timestamp == timestamp
    assert order.body.direction == Direction.SELL
    assert order.body.ticker == "BTC"
    assert order.body.qty == 5
    assert order.body.price == 1000
    assert order.filled == 0

def test_execution_details():
    """Тест создания деталей исполнения"""
    timestamp = datetime.now(UTC)
    execution = ExecutionDetails(
        execution_id=uuid4(),
        timestamp=timestamp,
        quantity=10,
        price=1000,
        counterparty_order_id=uuid4()
    )
    assert execution.execution_id is not None
    assert execution.timestamp == timestamp
    assert execution.quantity == 10
    assert execution.price == 1000
    assert execution.counterparty_order_id is not None

def test_order_execution_summary():
    """Тест создания сводки по исполнению"""
    timestamp = datetime.now(UTC)
    execution1 = ExecutionDetails(
        execution_id=uuid4(),
        timestamp=timestamp,
        quantity=4,
        price=1000,
        counterparty_order_id=uuid4()
    )
    execution2 = ExecutionDetails(
        execution_id=uuid4(),
        timestamp=timestamp,
        quantity=6,
        price=1100,
        counterparty_order_id=uuid4()
    )
    summary = OrderExecutionSummary(
        total_filled=10,
        average_price=1060.0,
        last_execution_time=timestamp,
        executions=[execution1, execution2]
    )
    assert summary.total_filled == 10
    assert summary.average_price == 1060.0
    assert summary.last_execution_time == timestamp
    assert len(summary.executions) == 2
    assert summary.executions[0] == execution1
    assert summary.executions[1] == execution2 