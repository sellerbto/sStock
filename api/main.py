from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .models import (
    NewUser, User, LoginUser, Balance,
    MarketOrder, LimitOrder, MarketOrderBody, LimitOrderBody,
    CreateOrderResponse, OrderStatus, Direction,
    ExecutionDetails, OrderExecutionSummary,
    Instrument, Ok, DepositRequest, WithdrawRequest
)
from .database import db
from .auth import get_current_user, get_admin_user
import os
import uuid
from datetime import datetime, UTC
from typing import Union, List, Optional

app = FastAPI(
    title="Stock Exchange",
    description="A stock exchange trading platform",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="api/static"), name="static")

@app.get("/")
async def root():
    try:
        return FileResponse("api/static/index.html", media_type="text/html")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/public/register", response_model=User)
async def register(new_user: NewUser):
    # Проверяем, не существует ли уже пользователь с таким именем
    if db.get_user_by_name(new_user.name):
        raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")

    user = User.create(name=new_user.name, password=new_user.password)
    db.add_user(user)
    return user

@app.post("/api/v1/public/login", response_model=User)
async def login(login_data: LoginUser):
    user = db.get_user_by_name(login_data.name)
    if not user or not user.check_password(login_data.password):
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
    return user

@app.get("/api/v1/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/api/v1/balance")
async def get_balances(current_user: User = Depends(get_current_user)):
    balance = db.get_balance(current_user.id)
    return balance.balances

@app.post("/api/v1/order", response_model=CreateOrderResponse)
async def create_order(
    order_data: Union[MarketOrderBody, LimitOrderBody],
    current_user: User = Depends(get_current_user)
):
    """Создание новой заявки (рыночной или лимитной)"""

    # Проверяем баланс пользователя
    balance = db.get_balance(current_user.id)

    if order_data.direction == Direction.SELL:
        # Проверяем достаточно ли токенов для продажи
        available_amount = balance.balances.get(order_data.ticker, 0)
        if available_amount < order_data.qty:
            return CreateOrderResponse(
                order_id=uuid.uuid4(),
                success=False,
                status=OrderStatus.REJECTED,
                rejection_reason=f"Недостаточно токенов {order_data.ticker} для продажи"
            )
    else:  # Direction.BUY
        # Для рыночной заявки на покупку проверяем наличие денег по лучшей цене
        if isinstance(order_data, MarketOrderBody):
            best_price = db.get_best_price(order_data.ticker, Direction.BUY)
            if best_price is None:
                return CreateOrderResponse(
                    order_id=uuid.uuid4(),
                    success=False,
                    status=OrderStatus.REJECTED,
                    rejection_reason="Нет доступных предложений для покупки"
                )
            required_usd = best_price * order_data.qty
            available_usd = balance.balances.get("USD", 0)
            if available_usd < required_usd:
                return CreateOrderResponse(
                    order_id=uuid.uuid4(),
                    success=False,
                    status=OrderStatus.REJECTED,
                    rejection_reason=f"Недостаточно USD для покупки. Требуется: {required_usd}, доступно: {available_usd}"
                )
        else:  # LimitOrderBody
            required_usd = order_data.price * order_data.qty
            available_usd = balance.balances.get("USD", 0)
            if available_usd < required_usd:
                return CreateOrderResponse(
                    order_id=uuid.uuid4(),
                    success=False,
                    status=OrderStatus.REJECTED,
                    rejection_reason=f"Недостаточно USD для покупки. Требуется: {required_usd}, доступно: {available_usd}"
                )

    order_id = uuid.uuid4()
    timestamp = datetime.now(UTC)

    if isinstance(order_data, MarketOrderBody):
        order = MarketOrder(
            id=order_id,
            status=OrderStatus.NEW,
            user_id=current_user.id,
            timestamp=timestamp,
            body=order_data
        )
        db.add_market_order(order)
        # Сразу пытаемся исполнить рыночную заявку
        db.execute_market_order(order)
    else:
        order = LimitOrder(
            id=order_id,
            status=OrderStatus.NEW,
            user_id=current_user.id,
            timestamp=timestamp,
            body=order_data
        )
        db.add_limit_order(order)

    return CreateOrderResponse(
        order_id=order_id,
        success=True,
        status=order.status
    )

@app.get("/api/v1/order")
async def list_orders(
    current_user: User = Depends(get_current_user),
    status: Optional[OrderStatus] = None,
    ticker: Optional[str] = None,
    limit: int = Query(default=100, le=1000)
):
    """Получение списка заявок пользователя с возможностью фильтрации"""
    orders = db.get_user_orders(current_user.id)
    
    # Применяем фильтры
    if status:
        orders = [order for order in orders if order.status == status]
    if ticker:
        orders = [order for order in orders if order.body.ticker == ticker]
    
    # Ограничиваем количество результатов
    return orders[:limit]

@app.get("/api/v1/order/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user)
):
    """Получение информации о конкретной заявке"""
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к этой заявке")
    return order

@app.get("/api/v1/order/{order_id}/executions")
async def get_order_executions(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user)
) -> List[ExecutionDetails]:
    """Получение истории исполнений заявки"""
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к этой заявке")
    return db.get_order_executions(order_id)

@app.get("/api/v1/order/{order_id}/summary")
async def get_order_summary(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user)
) -> Optional[OrderExecutionSummary]:
    """Получение сводки по исполнению заявки"""
    order = db.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к этой заявке")
    return db.get_order_execution_summary(order_id)

# Административные эндпоинты

@app.delete("/api/v1/admin/user/{user_id}", response_model=User)
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_admin_user)
):
    """Удаление пользователя"""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Проверяем, что пользователь не пытается удалить сам себя
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    db.delete_user(user_id)
    return user

@app.post("/api/v1/admin/instrument", response_model=Ok)
async def add_instrument(
    instrument: Instrument,
    current_user: User = Depends(get_admin_user)
):
    """Добавление нового торгового инструмента"""
    if db.get_instrument(instrument.ticker):
        raise HTTPException(status_code=400, detail="Instrument already exists")
    
    db.add_instrument(instrument)
    return Ok()

@app.delete("/api/v1/admin/instrument/{ticker}", response_model=Ok)
async def delete_instrument(
    ticker: str,
    current_user: User = Depends(get_admin_user)
):
    """Удаление торгового инструмента"""
    if not db.get_instrument(ticker):
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    # Проверяем, нет ли активных заявок по этому инструменту
    if db.has_active_orders(ticker):
        raise HTTPException(status_code=400, detail="Cannot delete instrument with active orders")
    
    db.delete_instrument(ticker)
    return Ok()

@app.post("/api/v1/admin/balance/deposit", response_model=Ok)
async def deposit(
    request: DepositRequest,
    current_user: User = Depends(get_admin_user)
):
    """Пополнение баланса пользователя"""
    user = db.get_user_by_id(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Проверяем существование инструмента
    if not db.get_instrument(request.ticker):
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    db.update_balance(request.user_id, request.ticker, request.amount)
    return Ok()

@app.post("/api/v1/admin/balance/withdraw", response_model=Ok)
async def withdraw_balance(
    request: WithdrawRequest,
    current_user: User = Depends(get_admin_user)
):
    """Вывод средств с баланса пользователя"""
    user = db.get_user_by_id(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    instrument = db.get_instrument(request.ticker)
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    
    balance = db.get_balance(user.id)
    if balance.balances.get(request.ticker, 0) < request.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    try:
        db.update_balance(user.id, request.ticker, -request.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Ok(success=True)
