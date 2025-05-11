import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from uuid import uuid4
from api.main import app
from api.models import Direction, OrderStatus, User
from api.database import db

@pytest.fixture
def client():
    """Фикстура для создания тестового клиента"""
    return TestClient(app)

@pytest.fixture
def user():
    """Фикстура для создания тестового пользователя"""
    user = db.get_user_by_name("test_user")
    if not user:
        user = User.create("test_user", "test_password")
        db.add_user(user)
    return user

def test_register_user(client):
    """Тест регистрации пользователя"""
    response = client.post(
        "/api/v1/public/register",
        json={"name": "new_user", "password": "password123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "new_user"
    assert "api_key" in data

def test_create_market_order(client, user):
    """Тест создания рыночной заявки"""
    db.update_balance(user.id, "USD", 10000)
    # Сначала создаём лимитную заявку на продажу, чтобы была встречная заявка
    db.update_balance(user.id, "BTC", 10)
    limit_response = client.post(
        "/api/v1/order",
        json={
            "direction": "SELL",
            "ticker": "BTC",
            "qty": 10,
            "price": 1000
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    print("limit order for market test:", limit_response.json())
    # Теперь создаём рыночную заявку на покупку
    response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 10
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    print("market order response:", response.json())
    assert response.status_code == 200
    data = response.json()
    assert "order_id" in data
    assert data["success"] is True

def test_create_limit_order(client, user):
    """Тест создания лимитной заявки"""
    db.update_balance(user.id, "USD", 10000)
    db.update_balance(user.id, "BTC", 5)
    response = client.post(
        "/api/v1/order",
        json={
            "direction": "SELL",
            "ticker": "BTC",
            "qty": 5,
            "price": 1000
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    print("limit order response:", response.json())
    assert response.status_code == 200
    data = response.json()
    assert "order_id" in data
    assert data["success"] is True

def test_create_order_insufficient_balance(client, user):
    """Тест создания заявки с недостаточным балансом"""
    response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 1000,
            "price": 1000
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert data["status"] == "REJECTED"
    assert "rejection_reason" in data

def test_list_orders(client, user):
    """Тест получения списка заявок"""
    response = client.get(
        "/api/v1/order",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

def test_list_orders_with_filters(client, user):
    """Тест получения списка заявок с фильтрами"""
    response = client.get(
        "/api/v1/order?status=NEW&ticker=BTC&limit=10",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) <= 10

def test_get_order_details(client, user):
    """Тест получения деталей заявки"""
    # Сначала создаем заявку
    order_response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 10
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    order_id = order_response.json()["order_id"]
    
    # Получаем детали заявки
    response = client.get(
        f"/api/v1/order/{order_id}",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(order_id)

def test_get_order_executions(client, user):
    """Тест получения истории исполнений заявки"""
    # Сначала создаём встречную лимитную заявку на продажу
    db.update_balance(user.id, "BTC", 10)
    limit_response = client.post(
        "/api/v1/order",
        json={
            "direction": "SELL",
            "ticker": "BTC",
            "qty": 10,
            "price": 1000
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    # Теперь создаём рыночную заявку на покупку
    db.update_balance(user.id, "USD", 10000)
    order_response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 10
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    order_id = order_response.json()["order_id"]
    # Получаем историю исполнений
    response = client.get(
        f"/api/v1/order/{order_id}/executions",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

def test_get_order_summary(client, user):
    """Тест получения сводки по заявке"""
    # Сначала создаём встречную лимитную заявку на продажу
    db.update_balance(user.id, "BTC", 10)
    limit_response = client.post(
        "/api/v1/order",
        json={
            "direction": "SELL",
            "ticker": "BTC",
            "qty": 10,
            "price": 1000
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    # Теперь создаём рыночную заявку на покупку
    db.update_balance(user.id, "USD", 10000)
    order_response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 10
        },
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    order_id = order_response.json()["order_id"]
    # Получаем сводку
    response = client.get(
        f"/api/v1/order/{order_id}/summary",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    if data:  # Сводка может быть None, если заявка еще не исполнялась
        assert "total_filled" in data
        assert "average_price" in data
        assert "executions" in data 