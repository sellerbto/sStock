import pytest
from uuid import uuid4
from datetime import datetime, UTC

from api.database import Database
from api.models import (
    User,
    Instrument,
    Direction,
    MarketOrder,
    MarketOrderBody,
    LimitOrder,
    LimitOrderBody,
    OrderStatus,
)

# Test database connection
db = Database("postgresql://postgres:postgres@db:5432/stock_exchange")

def setup_module():
    """Setup test data before running tests"""
    # Create test users
    users = [
        User(id=uuid4(), name="user1", role="user", api_key="key1"),
        User(id=uuid4(), name="user2", role="user", api_key="key2"),
        User(id=uuid4(), name="user3", role="user", api_key="key3"),
        User(id=uuid4(), name="user4", role="user", api_key="key4"),
    ]
    
    for user in users:
        db.add_user(user)
    
    # Create test instrument
    instrument = Instrument(ticker="TEST", name="Test Instrument")
    db.add_instrument(instrument)
    
    # Deposit initial balances
    # User1: 1000 RUB, 100 TEST
    # User2: 2000 RUB, 200 TEST
    # User3: 3000 RUB, 300 TEST
    # User4: 4000 RUB, 400 TEST
    balances = [
        (users[0].id, "RUB", 1000),
        (users[0].id, "TEST", 100),
        (users[1].id, "RUB", 2000),
        (users[1].id, "TEST", 200),
        (users[2].id, "RUB", 3000),
        (users[2].id, "TEST", 300),
        (users[3].id, "RUB", 4000),
        (users[3].id, "TEST", 400),
    ]
    
    for user_id, ticker, amount in balances:
        db.deposit_balance(user_id, ticker, amount)
    
    return users

def test_price_time_priority():
    """Test that orders are executed in price-time priority order"""
    users = setup_module()
    
    # User1 and User2 place sell orders at different prices
    sell_order1 = LimitOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=users[0].id,
        timestamp=datetime.now(UTC),
        body=LimitOrderBody(
            direction=Direction.SELL,
            ticker="TEST",
            qty=50,
            price=100,  # Cheaper price
        ),
    )
    
    sell_order2 = LimitOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=users[1].id,
        timestamp=datetime.now(UTC),
        body=LimitOrderBody(
            direction=Direction.SELL,
            qty=50,
            price=110,  # More expensive price
        ),
    )
    
    # User3 places a market buy order
    buy_order = MarketOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=users[2].id,
        timestamp=datetime.now(UTC),
        body=MarketOrderBody(
            direction=Direction.BUY,
            ticker="TEST",
            qty=75,  # Will match with both sell orders
        ),
    )
    
    # Place the orders
    db.add_limit_order(sell_order1)
    db.add_limit_order(sell_order2)
    db.add_market_order(buy_order)
    
    # Check that the cheaper order was executed first
    sell_order1_executed = db.get_order(sell_order1.id)
    sell_order2_executed = db.get_order(sell_order2.id)
    
    assert sell_order1_executed.status == OrderStatus.EXECUTED
    assert sell_order2_executed.status == OrderStatus.PARTIALLY_EXECUTED
    assert sell_order2_executed.filled == 25  # Only 25 units executed at higher price

def test_multiple_price_levels():
    """Test execution across multiple price levels"""
    users = setup_module()
    
    # Place multiple sell orders at different price levels
    sell_orders = [
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[0].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=30,
                price=100,  # Level 1
            ),
        ),
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[1].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=30,
                price=100,  # Level 1
            ),
        ),
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[2].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=30,
                price=110,  # Level 2
            ),
        ),
    ]
    
    # Place a large market buy order
    buy_order = MarketOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=users[3].id,
        timestamp=datetime.now(UTC),
        body=MarketOrderBody(
            direction=Direction.BUY,
            ticker="TEST",
            qty=80,  # Will match with all sell orders
        ),
    )
    
    # Place the orders
    for order in sell_orders:
        db.add_limit_order(order)
    db.add_market_order(buy_order)
    
    # Check execution results
    for order in sell_orders:
        executed_order = db.get_order(order.id)
        if order.body.price == 100:
            assert executed_order.status == OrderStatus.EXECUTED
        else:
            assert executed_order.status == OrderStatus.PARTIALLY_EXECUTED
            assert executed_order.filled == 20  # Only 20 units executed at higher price

def test_same_price_time_priority():
    """Test that orders at the same price are executed in time priority"""
    users = setup_module()
    
    # Place multiple sell orders at the same price but different times
    sell_orders = [
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[0].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=20,
                price=100,
            ),
        ),
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[1].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=20,
                price=100,
            ),
        ),
    ]
    
    # Place a market buy order
    buy_order = MarketOrder(
        id=uuid4(),
        status=OrderStatus.NEW,
        user_id=users[2].id,
        timestamp=datetime.now(UTC),
        body=MarketOrderBody(
            direction=Direction.BUY,
            ticker="TEST",
            qty=30,  # Will match with first order and part of second
        ),
    )
    
    # Place the orders
    for order in sell_orders:
        db.add_limit_order(order)
    db.add_market_order(buy_order)
    
    # Check execution results
    first_order = db.get_order(sell_orders[0].id)
    second_order = db.get_order(sell_orders[1].id)
    
    assert first_order.status == OrderStatus.EXECUTED
    assert second_order.status == OrderStatus.PARTIALLY_EXECUTED
    assert second_order.filled == 10  # Only 10 units executed from second order

def test_orderbook_levels():
    """Test that orderbook correctly aggregates orders at the same price level"""
    users = setup_module()
    
    # Place multiple sell orders at different price levels
    sell_orders = [
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[0].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=20,
                price=100,
            ),
        ),
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[1].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=20,
                price=100,
            ),
        ),
        LimitOrder(
            id=uuid4(),
            status=OrderStatus.NEW,
            user_id=users[2].id,
            timestamp=datetime.now(UTC),
            body=LimitOrderBody(
                direction=Direction.SELL,
                ticker="TEST",
                qty=20,
                price=110,
            ),
        ),
    ]
    
    # Place the orders
    for order in sell_orders:
        db.add_limit_order(order)
    
    # Get orderbook
    orderbook = db.get_orderbook("TEST")
    
    # Check that orders at the same price are aggregated
    assert len(orderbook.ask_levels) == 2  # Two price levels
    assert orderbook.ask_levels[0].price == 100
    assert orderbook.ask_levels[0].qty == 40  # 20 + 20 at price 100
    assert orderbook.ask_levels[1].price == 110
    assert orderbook.ask_levels[1].qty == 20  # 20 at price 110 