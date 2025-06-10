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

def get_auth_header(token: str) -> dict:
    """Вспомогательная функция для создания заголовка авторизации"""
    return {"Authorization": f"TOKEN {token}"}

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

def test_register_duplicate_user(client, user):
    """Тест регистрации пользователя с существующим именем"""
    response = client.post(
        "/api/v1/public/register",
        json={"name": user.name, "password": "password123"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Пользователь с таким именем уже существует"

def test_login_success(client, user):
    """Тест успешной авторизации"""
    response = client.post(
        "/api/v1/public/login",
        json={"name": user.name, "password": "test_password"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == user.name
    assert data["api_key"] == user.api_key

def test_login_wrong_password(client, user):
    """Тест авторизации с неверным паролем"""
    response = client.post(
        "/api/v1/public/login",
        json={"name": user.name, "password": "wrong_password"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверное имя пользователя или пароль"

def test_login_nonexistent_user(client):
    """Тест авторизации несуществующего пользователя"""
    response = client.post(
        "/api/v1/public/login",
        json={"name": "nonexistent", "password": "password123"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверное имя пользователя или пароль"

def test_get_me_unauthorized(client):
    """Тест получения информации о себе без авторизации"""
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authorization header is missing"

def test_get_me_invalid_token(client):
    """Тест получения информации о себе с неверным токеном"""
    response = client.get("/api/v1/me", headers={"Authorization": "TOKEN invalid_token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"

def test_get_me_success(client, user):
    """Тест успешного получения информации о себе"""
    response = client.get("/api/v1/me", headers=get_auth_header(user.api_key))
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == user.name
    assert data["api_key"] == user.api_key

def test_create_market_order(client, user):
    """Тест создания рыночной заявки"""
    db.update_balance(user.id, "RUB", 10000)
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
        headers=get_auth_header(user.api_key)
    )
    assert limit_response.status_code == 200
    # Теперь создаём рыночную заявку на покупку
    response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 10
        },
        headers=get_auth_header(user.api_key)
    )
    assert response.status_code == 200
    data = response.json()
    assert "order_id" in data
    assert data["success"] is True

def test_create_limit_order(client, user):
    """Тест создания лимитной заявки"""
    db.update_balance(user.id, "RUB", 10000)
    db.update_balance(user.id, "BTC", 5)
    response = client.post(
        "/api/v1/order",
        json={
            "direction": "SELL",
            "ticker": "BTC",
            "qty": 5,
            "price": 1000
        },
        headers=get_auth_header(user.api_key)
    )
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
        headers=get_auth_header(user.api_key)
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
        headers=get_auth_header(user.api_key)
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

def test_list_orders_with_filters(client, user):
    """Тест получения списка заявок с фильтрами"""
    response = client.get(
        "/api/v1/order?status=NEW&ticker=BTC&limit=10",
        headers=get_auth_header(user.api_key)
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
        headers=get_auth_header(admin.api_key)
    )
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Russian Ruble", "ticker": "RUB"},
        headers=get_auth_header(admin.api_key)
    )
    # Пополняем баланс пользователя BTC и RUB
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": str(user.id), "ticker": "BTC", "amount": 10},
        headers=get_auth_header(admin.api_key)
    )
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": str(user.id), "ticker": "RUB", "amount": 100000},
        headers=get_auth_header(admin.api_key)
    )
    # Сначала создаём лимитную заявку на продажу BTC
    sell_order = client.post(
        "/api/v1/order",
        json={"direction": "SELL", "ticker": "BTC", "qty": 10, "price": 1000},
        headers=get_auth_header(user.api_key)
    )
    assert sell_order.status_code == 200
    # Теперь создаём рыночную заявку на покупку BTC
    buy_order = client.post(
        "/api/v1/order",
        json={"direction": "BUY", "ticker": "BTC", "qty": 10},
        headers=get_auth_header(user.api_key)
    )
    assert buy_order.status_code == 200
    order_id = buy_order.json()["order_id"]
    # Получаем детали заявки
    response = client.get(
        f"/api/v1/order/{order_id}",
        headers=get_auth_header(user.api_key)
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
        headers=get_auth_header(user.api_key)
    )
    # Теперь создаём рыночную заявку на покупку
    db.update_balance(user.id, "RUB", 10000)
    order_response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 10
        },
        headers=get_auth_header(user.api_key)
    )
    order_id = order_response.json()["order_id"]
    # Получаем историю исполнений
    response = client.get(
        f"/api/v1/order/{order_id}/executions",
        headers=get_auth_header(user.api_key)
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
        headers=get_auth_header(user.api_key)
    )
    # Теперь создаём рыночную заявку на покупку
    db.update_balance(user.id, "RUB", 10000)
    order_response = client.post(
        "/api/v1/order",
        json={
            "direction": "BUY",
            "ticker": "BTC",
            "qty": 10
        },
        headers=get_auth_header(user.api_key)
    )
    order_id = order_response.json()["order_id"]
    # Получаем сводку
    response = client.get(
        f"/api/v1/order/{order_id}/summary",
        headers=get_auth_header(user.api_key)
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_qty" in data
    assert "avg_price" in data

def test_delete_user(client, admin, user):
    """Тест удаления пользователя"""
    response = client.delete(
        f"/api/v1/admin/user/{user.id}",
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user.id)

def test_delete_user_self(client, admin):
    """Тест попытки удаления самого себя"""
    response = client.delete(
        f"/api/v1/admin/user/{admin.id}",
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot delete yourself"

def test_delete_user_unauthorized(client, user):
    """Тест попытки удаления пользователя без прав администратора"""
    response = client.delete(
        f"/api/v1/admin/user/{user.id}",
        headers=get_auth_header(user.api_key)
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough permissions. Admin role required"

def test_add_instrument(client, admin, reset_db):
    """Тест добавления нового инструмента"""
    response = client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_add_duplicate_instrument(client, admin, reset_db):
    """Тест добавления существующего инструмента"""
    # Сначала добавляем инструмент
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    # Пытаемся добавить его снова
    response = client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Instrument already exists"

def test_delete_instrument(client, admin, reset_db):
    """Тест удаления инструмента"""
    # Сначала добавляем инструмент
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    # Теперь удаляем его
    response = client.delete(
        "/api/v1/admin/instrument/BTC",
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_delete_nonexistent_instrument(client, admin, reset_db):
    """Тест удаления несуществующего инструмента"""
    response = client.delete(
        "/api/v1/admin/instrument/NONEXISTENT",
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Instrument not found"

def test_deposit_balance(client, admin, user, reset_db):
    """Тест пополнения баланса пользователя"""
    # Сначала добавляем инструмент
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    # Пополняем баланс
    response = client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": str(user.id), "ticker": "BTC", "amount": 10},
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    # Проверяем, что баланс обновился
    balance = db.get_balance(user.id)
    assert balance.balances.get("BTC", 0) == 10

def test_withdraw_balance(client, admin, user, reset_db):
    """Тест списания средств с баланса пользователя"""
    # Сначала добавляем инструмент
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    # Пополняем баланс
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": str(user.id), "ticker": "BTC", "amount": 10},
        headers=get_auth_header(admin.api_key)
    )
    # Списываем средства
    response = client.post(
        "/api/v1/admin/balance/withdraw",
        json={"user_id": str(user.id), "ticker": "BTC", "amount": 5},
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    # Проверяем, что баланс обновился
    balance = db.get_balance(user.id)
    assert balance.balances.get("BTC", 0) == 5

def test_withdraw_insufficient_balance(client, admin, user, reset_db):
    """Тест списания средств при недостаточном балансе"""
    # Сначала добавляем инструмент
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    # Пополняем баланс
    client.post(
        "/api/v1/admin/balance/deposit",
        json={"user_id": str(user.id), "ticker": "BTC", "amount": 10},
        headers=get_auth_header(admin.api_key)
    )
    # Пытаемся списать больше, чем есть
    response = client.post(
        "/api/v1/admin/balance/withdraw",
        json={"user_id": str(user.id), "ticker": "BTC", "amount": 20},
        headers=get_auth_header(admin.api_key)
    )
    assert response.status_code == 400
    assert "Insufficient balance" in response.json()["detail"]

def test_get_orderbook(client, admin, reset_db):
    """Тест получения стакана заявок"""
    # Добавляем инструмент
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    # Получаем стакан
    response = client.get("/api/v1/public/orderbook/BTC")
    assert response.status_code == 200
    data = response.json()
    assert "bids" in data
    assert "asks" in data

def test_get_orderbook_nonexistent_instrument(client):
    """Тест получения стакана несуществующего инструмента"""
    response = client.get("/api/v1/public/orderbook/NONEXISTENT")
    assert response.status_code == 404
    assert response.json()["detail"] == "Instrument not found"

def test_get_orderbook_limit(client, user, admin, reset_db):
    """Тест получения стакана с ограничением количества уровней"""
    # Добавляем инструмент
    client.post(
        "/api/v1/admin/instrument",
        json={"name": "Bitcoin", "ticker": "BTC"},
        headers=get_auth_header(admin.api_key)
    )
    # Получаем стакан с ограничением
    response = client.get("/api/v1/public/orderbook/BTC?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data["bids"]) <= 5
    assert len(data["asks"]) <= 5 