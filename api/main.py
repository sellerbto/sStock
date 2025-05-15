from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from .models import (
    NewUser, User, LoginUser, Balance,
    MarketOrder, LimitOrder, MarketOrderBody, LimitOrderBody,
    CreateOrderResponse, OrderStatus, Direction,
    ExecutionDetails, OrderExecutionSummary,
    Instrument, Ok, DepositRequest, WithdrawRequest,
    L2OrderBook
)
from .database import db
from .auth import get_current_user, get_admin_user
import os
import uuid
from datetime import datetime, UTC
from typing import Union, List, Optional
from fastapi.openapi.utils import get_openapi

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

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.get("/")
async def root():
    try:
        return FileResponse("api/static/index.html", media_type="text/html")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/public/register", response_model=User)
async def register(new_user: NewUser):
    try:
        # Проверяем, не существует ли уже пользователь с таким именем
        if db.get_user_by_name(new_user.name):
            raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")

        user = User.create(name=new_user.name, password=new_user.password)
        db.add_user(user)
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/public/login", response_model=User)
async def login(login_data: LoginUser):
    try:
        user = db.get_user_by_name(login_data.name)
        if not user or not user.check_password(login_data.password):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/api/v1/balance")
async def get_balances(current_user: User = Depends(get_current_user)):
    try:
        balance = db.get_balance(current_user.id)
        return balance.balances
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/order", response_model=CreateOrderResponse)
async def create_order(
    order_data: Union[MarketOrderBody, LimitOrderBody],
    current_user: User = Depends(get_current_user)
):
    """Создание новой заявки (рыночной или лимитной)"""
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/order")
async def list_orders(
    current_user: User = Depends(get_current_user),
    status: Optional[OrderStatus] = None,
    ticker: Optional[str] = None,
    limit: int = Query(default=100, le=1000)
):
    """Получение списка заявок пользователя с возможностью фильтрации"""
    try:
        orders = db.get_user_orders(current_user.id)
        
        # Применяем фильтры
        if status:
            orders = [order for order in orders if order.status == status]
        if ticker:
            orders = [order for order in orders if order.body.ticker == ticker]
        
        # Ограничиваем количество результатов
        return orders[:limit]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/order/{order_id}", response_model=Union[MarketOrder, LimitOrder])
async def get_order(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user)
):
    """Получение информации о конкретной заявке"""
    try:
        order = db.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if order.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Нет доступа к этой заявке")
        return order
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/order/{order_id}/executions")
async def get_order_executions(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user)
) -> List[ExecutionDetails]:
    """Получение истории исполнений заявки"""
    try:
        order = db.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if order.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Нет доступа к этой заявке")
        return db.get_order_executions(order_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/order/{order_id}/summary")
async def get_order_summary(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user)
) -> Optional[OrderExecutionSummary]:
    """Получение сводки по исполнению заявки"""
    try:
        order = db.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if order.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Нет доступа к этой заявке")
        return db.get_order_execution_summary(order_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Административные эндпоинты

@app.delete("/api/v1/admin/user/{user_id}", response_model=User)
async def delete_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_admin_user)
):
    """Удаление пользователя"""
    try:
        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Проверяем, что пользователь не пытается удалить сам себя
        if user.id == current_user.id:
            raise HTTPException(status_code=400, detail="Cannot delete yourself")
        
        db.delete_user(user_id)
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/admin/instrument", response_model=Ok)
async def add_instrument(
    instrument: Instrument,
    current_user: User = Depends(get_admin_user)
):
    """Добавление нового торгового инструмента"""
    try:
        if db.get_instrument(instrument.ticker):
            raise HTTPException(status_code=400, detail="Instrument already exists")
        
        db.add_instrument(instrument)
        return Ok()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/admin/instrument/{ticker}", response_model=Ok)
async def delete_instrument(
    ticker: str,
    current_user: User = Depends(get_admin_user)
):
    """Удаление торгового инструмента"""
    try:
        if not db.get_instrument(ticker):
            raise HTTPException(status_code=404, detail="Instrument not found")
        
        # Проверяем, нет ли активных заявок по этому инструменту
        active_orders = db.get_active_orders_by_ticker(ticker)
        if active_orders:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete instrument with active orders"
            )
        
        db.delete_instrument(ticker)
        return Ok()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/admin/balance/deposit", response_model=Ok)
async def deposit(
    request: DepositRequest,
    current_user: User = Depends(get_admin_user)
):
    """Пополнение баланса пользователя"""
    try:
        user = db.get_user_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        db.deposit_balance(request.user_id, request.ticker, request.amount)
        return Ok()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/admin/balance/withdraw", response_model=Ok)
async def withdraw_balance(
    request: WithdrawRequest,
    current_user: User = Depends(get_admin_user)
):
    """Списание средств с баланса пользователя"""
    try:
        user = db.get_user_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        balance = db.get_balance(request.user_id)
        available_amount = balance.balances.get(request.ticker, 0)
        
        if available_amount < request.amount:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient balance. Available: {available_amount}, requested: {request.amount}"
            )
        
        db.withdraw_balance(request.user_id, request.ticker, request.amount)
        return Ok()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/public/instrument")
async def list_instruments():
    """Получение списка всех торговых инструментов"""
    try:
        return db.get_all_instruments()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/public/orderbook/{ticker}", response_model=L2OrderBook)
async def get_orderbook(ticker: str, limit: int = Query(default=10, le=25)):
    """Получение стакана заявок по инструменту"""
    try:
        if not db.get_instrument(ticker):
            raise HTTPException(status_code=404, detail="Instrument not found")
        return db.get_orderbook(ticker, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/public/transactions/{ticker}")
async def get_transactions(ticker: str):
    """Получение истории сделок по инструменту"""
    try:
        if not db.get_instrument(ticker):
            raise HTTPException(status_code=404, detail="Instrument not found")
        return db.get_transactions(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Добавляем схему авторизации X-API-Key в OpenAPI

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key"
        }
    }
    # По умолчанию требовать ключ для всех эндпоинтов (можно убрать, если не нужно)
    for path in openapi_schema["paths"].values():
        for method in path.values():
            method.setdefault("security", [{"ApiKeyAuth": []}])
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
