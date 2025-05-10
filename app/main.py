from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .models import (
    NewUser, User, LoginUser, Balance,
    MarketOrder, LimitOrder, MarketOrderBody, LimitOrderBody,
    CreateOrderResponse, OrderStatus
)
from .database import db
from .auth import get_current_user
import os
import uuid
from datetime import datetime
from typing import Union

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
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
async def root():
    try:
        return FileResponse("app/static/index.html", media_type="text/html")
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
            raise HTTPException(
                status_code=400,
                detail=f"Недостаточно токенов {order_data.ticker} для продажи"
            )
    
    order_id = uuid.uuid4()
    timestamp = datetime.utcnow().isoformat()

    if isinstance(order_data, MarketOrderBody):
        order = MarketOrder(
            id=order_id,
            status=OrderStatus.NEW,
            user_id=current_user.id,
            timestamp=timestamp,
            body=order_data
        )
        db.add_market_order(order)
    else:
        order = LimitOrder(
            id=order_id,
            status=OrderStatus.NEW,
            user_id=current_user.id,
            timestamp=timestamp,
            body=order_data,
            filled=0
        )
        db.add_limit_order(order)

    return CreateOrderResponse(order_id=order_id)

@app.get("/api/v1/order")
async def list_orders(current_user: User = Depends(get_current_user)):
    """Получение списка заявок пользователя"""
    return db.get_user_orders(current_user.id)

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
