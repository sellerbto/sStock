import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from uuid import uuid4
from api.main import app
from api.models import Direction, OrderStatus, User, UserRole, Instrument
from api.database import db

@pytest.fixture
def reset_db():
    db.users.clear()
    db.users_by_name.clear()
    db.users_by_id.clear()
    db.balances.clear()
    db.market_orders.clear()
    db.limit_orders.clear()
    db.executions.clear()
    db.instruments.clear()
    yield

@pytest.fixture
def client():
    """Фикстура для создания тестового клиента"""
    return TestClient(app)

@pytest.fixture
def user(reset_db):
    """Фикстура для создания тестового пользователя"""
    user = db.get_user_by_name("test_user")
    if not user:
        user = User.create("test_user", "test_password")
        db.add_user(user)
    return user

@pytest.fixture
def admin(reset_db):
    """Фикстура для создания тестового администратора"""
    admin = db.get_user_by_name("test_admin")
    if not admin:
        admin = User.create("test_admin", "test_password", role=UserRole.ADMIN)
        db.add_user(admin)
    return admin

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

def test_get_order_details(client, user, admin, reset_db):
    """Тест получения деталей заявки"""
    # Добавляем инструмент BTC
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "US Dollar", "ticker": "USD"},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    # Пополняем баланс пользователя BTC и USD
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": str(user.id), "ticker": "BTC", "amount": 10},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": str(user.id), "ticker": "USD", "amount": 100000},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    # Сначала создаём лимитную заявку на продажу BTC
    sell_order = client.post(
        "/api/v1/order",
        json={"direction": "SELL", "ticker": "BTC", "qty": 10, "price": 1000},
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert sell_order.status_code == 200
    # Теперь создаём рыночную заявку на покупку BTC
    buy_order = client.post(
        "/api/v1/order",
        json={"direction": "BUY", "ticker": "BTC", "qty": 10},
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert buy_order.status_code == 200
    order_id = buy_order.json()["order_id"]
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

# Тесты административного API

def test_delete_user(client, admin, user):
    """Тест удаления пользователя"""
    response = client.delete(
        f"/api/v1/admin/user/{user.id}",
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user.id)
    assert data["name"] == user.name

def test_delete_user_self(client, admin):
    """Тест попытки удаления самого себя"""
    response = client.delete(
        f"/api/v1/admin/user/{admin.id}",
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 400
    assert "Cannot delete yourself" in response.json()["detail"]

def test_delete_user_unauthorized(client, user):
    """Тест удаления пользователя без прав администратора"""
    response = client.delete(
        f"/api/v1/admin/user/{user.id}",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert response.status_code == 403

def test_add_instrument(client, admin, reset_db):
    """Тест добавления нового инструмента"""
    instrument = {
        "name": "Test Coin",
        "ticker": "TEST"
    }
    response = client.post(
        "/api/v1/admin/instrument",
        json=instrument,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_add_duplicate_instrument(client, admin, reset_db):
    """Тест добавления уже существующего инструмента"""
    instrument = {
        "name": "Test Coin",
        "ticker": "TEST"
    }
    client.post(
        "/api/v1/admin/instrument",
        json=instrument,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    response = client.post(
        "/api/v1/admin/instrument",
        json=instrument,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 400
    assert "Instrument already exists" in response.json()["detail"]

def test_delete_instrument(client, admin, reset_db):
    """Тест удаления инструмента"""
    instrument = {
        "name": "Test Coin",
        "ticker": "TEST"
    }
    client.post(
        "/api/v1/admin/instrument",
        json=instrument,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    response = client.delete(
        f"/api/v1/admin/instrument/{instrument['ticker']}",
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_delete_nonexistent_instrument(client, admin, reset_db):
    """Тест удаления несуществующего инструмента"""
    response = client.delete(
        "/api/v1/admin/instrument/NONEXISTENT",
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 404
    assert "Instrument not found" in response.json()["detail"]

def test_deposit_balance(client, admin, user, reset_db):
    """Тест пополнения баланса пользователя"""
    instrument = {
        "name": "Test Coin",
        "ticker": "TEST"
    }
    client.post(
        "/api/v1/admin/instrument",
        json=instrument,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    deposit_request = {
        "user_id": str(user.id),
        "ticker": "TEST",
        "amount": 1000
    }
    response = client.post(
        "/api/v1/admin/balance/deposit",
        json=deposit_request,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    balance_response = client.get(
        "/api/v1/balance",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert balance_response.status_code == 200
    assert balance_response.json()["TEST"] == 1000

def test_withdraw_balance(client, admin, user, reset_db):
    """Тест вывода средств с баланса пользователя"""
    instrument = {
        "name": "Test Coin",
        "ticker": "TEST"
    }
    client.post(
        "/api/v1/admin/instrument",
        json=instrument,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    deposit_request = {
        "user_id": str(user.id),
        "ticker": "TEST",
        "amount": 1000
    }
    client.post(
        "/api/v1/admin/balance/deposit",
        json=deposit_request,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    withdraw_request = {
        "user_id": str(user.id),
        "ticker": "TEST",
        "amount": 500
    }
    response = client.post(
        "/api/v1/admin/balance/withdraw",
        json=withdraw_request,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    balance_response = client.get(
        "/api/v1/balance",
        headers={"Authorization": f"Bearer {user.api_key}"}
    )
    assert balance_response.status_code == 200
    assert balance_response.json()["TEST"] == 500

def test_withdraw_insufficient_balance(client, admin, user, reset_db):
    """Тест попытки вывода средств при недостаточном балансе"""
    instrument = {
        "name": "Test Coin",
        "ticker": "TEST"
    }
    client.post(
        "/api/v1/admin/instrument",
        json=instrument,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    deposit_request = {
        "user_id": str(user.id),
        "ticker": "TEST",
        "amount": 1000
    }
    client.post(
        "/api/v1/admin/balance/deposit",
        json=deposit_request,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    withdraw_request = {
        "user_id": str(user.id),
        "ticker": "TEST",
        "amount": 2000
    }
    response = client.post(
        "/api/v1/admin/balance/withdraw",
        json=withdraw_request,
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    assert response.status_code == 400
    assert "Insufficient balance" in response.json()["detail"]

def test_matching_limit_orders(client, admin, reset_db):
    """Тест проверки встречных лимитных заявок между двумя пользователями"""
    # Регистрируем двух пользователей
    seller_resp = client.post(
        "/api/v1/public/register",
        json={"name": "seller", "password": "sellerpass"}
    )
    buyer_resp = client.post(
        "/api/v1/public/register",
        json={"name": "buyer", "password": "buyerpass"}
    )
    seller = seller_resp.json()
    buyer = buyer_resp.json()
    
    # Добавляем инструменты
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "US Dollar", "ticker": "USD"},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    # Пополняем балансы
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": seller["id"], "ticker": "BTC", "amount": 10},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": buyer["id"], "ticker": "USD", "amount": 10000},
        headers={"Authorization": f"Bearer {admin.api_key}"}
    )
    # seller выставляет лимитную заявку на продажу
    sell_order = client.post(
        "/api/v1/order",
        json={"direction": "SELL", "ticker": "BTC", "qty": 5, "price": 1000},
        headers={"Authorization": f"Bearer {seller['api_key']}"}
    )
    assert sell_order.status_code == 200
    sell_order_id = sell_order.json()["order_id"]
    # buyer выставляет встречную лимитную заявку на покупку
    buy_order = client.post(
        "/api/v1/order",
        json={"direction": "BUY", "ticker": "BTC", "qty": 5, "price": 1000},
        headers={"Authorization": f"Bearer {buyer['api_key']}"}
    )
    assert buy_order.status_code == 200
    buy_order_id = buy_order.json()["order_id"]
    # Проверяем статусы заявок
    sell_order_details = client.get(
        f"/api/v1/order/{sell_order_id}",
        headers={"Authorization": f"Bearer {seller['api_key']}"}
    )
    assert sell_order_details.status_code == 200
    assert sell_order_details.json()["status"] == "EXECUTED"
    buy_order_details = client.get(
        f"/api/v1/order/{buy_order_id}",
        headers={"Authorization": f"Bearer {buyer['api_key']}"}
    )
    assert buy_order_details.status_code == 200
    assert buy_order_details.json()["status"] == "EXECUTED"
    # Проверяем исполнения заявок
    sell_executions = client.get(
        f"/api/v1/order/{sell_order_id}/executions",
        headers={"Authorization": f"Bearer {seller['api_key']}"}
    )
    assert sell_executions.status_code == 200
    assert len(sell_executions.json()) == 1
    buy_executions = client.get(
        f"/api/v1/order/{buy_order_id}/executions",
        headers={"Authorization": f"Bearer {buyer['api_key']}"}
    )
    assert buy_executions.status_code == 200
    assert len(buy_executions.json()) == 1
    # Проверяем балансы после исполнения
    seller_balance = client.get(
        "/api/v1/balance",
        headers={"Authorization": f"Bearer {seller['api_key']}"}
    )
    assert seller_balance.status_code == 200
    seller_balance_data = seller_balance.json()
    assert seller_balance_data["BTC"] == 5  # 10 - 5
    assert seller_balance_data["USD"] == 5000  # 0 + 5*1000
    buyer_balance = client.get(
        "/api/v1/balance",
        headers={"Authorization": f"Bearer {buyer['api_key']}"}
    )
    assert buyer_balance.status_code == 200
    buyer_balance_data = buyer_balance.json()
    assert buyer_balance_data["BTC"] == 5  # 0 + 5
    assert buyer_balance_data["USD"] == 5000  # 10000 - 5*1000 