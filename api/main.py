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
    L2OrderBook, UserRole
)
from .database import db, Database, DatabaseError, DatabaseIntegrityError, DatabaseNotFoundError
from .auth import get_current_user, get_admin_user
import os
import uuid
from datetime import datetime, UTC
from typing import Union, List, Optional
from fastapi.openapi.utils import get_openapi
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
import logging
import time
# from dotenv import load_dotenv

# Load environment variables
# load_dotenv()

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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Получаем API ключ из заголовка
    api_key = request.headers.get("Authorization", "").replace("TOKEN ", "")
    
    # Логируем информацию о запросе
    logger.info(f"Request: {request.method} {request.url.path} - API Key: {api_key}")
    
    # Замеряем время выполнения
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # Логируем результат
    logger.info(f"Response: {request.method} {request.url.path} - Status: {response.status_code} - Time: {process_time:.2f}s")
    
    return response

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )

@app.exception_handler(DatabaseError)
async def database_exception_handler(request: Request, exc: DatabaseError):
    if isinstance(exc, DatabaseIntegrityError):
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc)}
        )
    elif isinstance(exc, DatabaseNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)}
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Database error: {str(exc)}"}
        )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )

@app.post("/api/v1/public/register", response_model=User, tags=["public"])
async def register(new_user: NewUser):
    """Регистрация нового пользователя"""
    try:
        # Проверяем, не существует ли уже пользователь с таким именем
        if db.get_user_by_name(new_user.name):
            raise HTTPException(status_code=400, detail="User with this name already exists")
            
        if not new_user.name.strip():
            raise HTTPException(status_code=400, detail="Username cannot be empty")
            
        if not new_user.name.isascii():
            raise HTTPException(status_code=400, detail="Username must contain only ASCII characters")
            
        if not new_user.name.isalnum():
            raise HTTPException(status_code=400, detail="Username must contain only letters and numbers")
            
        if len(new_user.name) < 3:
            raise HTTPException(status_code=400, detail="Username must be at least 3 characters long")
            
        if len(new_user.name) > 50:
            raise HTTPException(status_code=400, detail="Username must be at most 50 characters long")

        user = User(
            id=uuid.uuid4(),
            name=new_user.name,
            role=UserRole.USER,
            api_key=f"key-{uuid.uuid4()}"
        )
        db.add_user(user)
        return user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/balance", tags=["balance"])
async def get_balances(current_user: User = Depends(get_current_user)):
    """Получение баланса пользователя"""
    try:
        balance = db.get_balance(current_user.id)
        return balance.balances
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/order", response_model=CreateOrderResponse, tags=["order"])
async def create_order(
    order_data: Union[MarketOrderBody, LimitOrderBody],
    current_user: User = Depends(get_current_user)
):
    """Создание новой заявки (рыночной или лимитной)"""
    try:
        # Проверяем, что тикер существует
        if not db.get_instrument(order_data.ticker):
            raise HTTPException(status_code=404, detail="Instrument not found")
            
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/order", tags=["order"])
async def list_orders(
    current_user: User = Depends(get_current_user),
    status: Optional[OrderStatus] = None,
    ticker: Optional[str] = None,
    limit: int = Query(default=100, le=1000)
):
    """Получение списка заявок пользователя"""
    try:
        if ticker and not db.get_instrument(ticker):
            raise HTTPException(status_code=404, detail="Instrument not found")
            
        return db.get_user_orders(current_user.id, status, ticker, limit)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/order/{order_id}", response_model=Union[MarketOrder, LimitOrder], tags=["order"])
async def get_order(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_user)
):
    """Получение информации о заявке"""
    try:
        order = db.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return order
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/v1/order/{order_id}/executions")
# async def get_order_executions(
#     order_id: uuid.UUID,
#     current_user: User = Depends(get_current_user)
# ) -> List[ExecutionDetails]:
#     """Получение истории исполнений заявки"""
#     try:
#         order = db.get_order(order_id)
#         if not order:
#             raise HTTPException(status_code=404, detail="Order not found")
#         if order.user_id != current_user.id:
#             raise HTTPException(status_code=403, detail="Not enough permissions")
#         return db.get_order_executions(order_id)
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @app.get("/api/v1/order/{order_id}/summary")
# async def get_order_summary(
#     order_id: uuid.UUID,
#     current_user: User = Depends(get_current_user)
# ) -> Optional[OrderExecutionSummary]:
#     """Получение сводки по исполнению заявки"""
#     try:
#         order = db.get_order(order_id)
#         if not order:
#             raise HTTPException(status_code=404, detail="Order not found")
#         if order.user_id != current_user.id:
#             raise HTTPException(status_code=403, detail="Not enough permissions")
#         return db.get_order_execution_summary(order_id)
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# Административные эндпоинты

@app.delete("/api/v1/admin/user/{user_id}", response_model=User, tags=["admin", "user"])
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/admin/instrument", response_model=Ok, tags=["admin"])
async def add_instrument(
    instrument: Instrument,
    current_user: User = Depends(get_admin_user)
):
    """Добавление нового торгового инструмента"""
    try:
        logger.info(f"Attempting to add instrument: {instrument.ticker} by user {current_user.name}")
        
        # Проверяем, что тикер и название не пустые
        if not instrument.ticker.strip():
            logger.warning(f"Empty ticker provided by user {current_user.name}")
            raise HTTPException(status_code=400, detail="Ticker cannot be empty")
        if not instrument.name.strip():
            logger.warning(f"Empty name provided for ticker {instrument.ticker} by user {current_user.name}")
            raise HTTPException(status_code=400, detail="Name cannot be empty")
            
        # Проверяем, что тикер содержит только буквы и цифры
        if not instrument.ticker.isalnum():
            logger.warning(f"Invalid ticker format: {instrument.ticker} by user {current_user.name}")
            raise HTTPException(status_code=400, detail="Ticker must contain only letters and numbers")
            
        # Проверяем, что инструмент еще не существует
        if db.get_instrument(instrument.ticker):
            logger.warning(f"Attempt to add existing instrument: {instrument.ticker} by user {current_user.name}")
            raise HTTPException(status_code=400, detail="Instrument already exists")
        
        db.add_instrument(instrument)
        logger.info(f"Successfully added instrument: {instrument.ticker} by user {current_user.name}")
        return Ok()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding instrument {instrument.ticker} by user {current_user.name}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/admin/instrument/{ticker}", response_model=Ok, tags=["admin"])
async def delete_instrument(
    ticker: str,
    current_user: User = Depends(get_admin_user)
):
    """Удаление торгового инструмента"""
    try:
        if not ticker.strip():
            raise HTTPException(status_code=400, detail="Ticker cannot be empty")
            
        if not ticker.isalnum():
            raise HTTPException(status_code=400, detail="Ticker must contain only letters and numbers")
            
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/admin/balance/deposit", response_model=Ok, tags=["balance", "admin"])
async def deposit(
    request: DepositRequest,
    current_user: User = Depends(get_admin_user)
):
    """Пополнение баланса пользователя"""
    try:
        user = db.get_user_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        if request.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
            
        if request.ticker == "USD" and not request.amount.is_integer():
            raise HTTPException(status_code=400, detail="USD amount must be integer")
            
        db.deposit_balance(request.user_id, request.ticker, request.amount)
        return Ok()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/admin/balance/withdraw", response_model=Ok, tags=["balance", "admin"])
async def withdraw_balance(
    request: WithdrawRequest,
    current_user: User = Depends(get_admin_user)
):
    """Списание средств с баланса пользователя"""
    try:
        user = db.get_user_by_id(request.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        if request.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
            
        if request.ticker == "USD" and not request.amount.is_integer():
            raise HTTPException(status_code=400, detail="USD amount must be integer")
            
        balance = db.get_balance(request.user_id)
        available_amount = balance.balances.get(request.ticker, 0)
        
        if available_amount < request.amount:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient balance. Available: {available_amount}, requested: {request.amount}"
            )
        
        db.withdraw_balance(request.user_id, request.ticker, request.amount)
        return Ok()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/public/instrument", tags=["public"])
async def list_instruments():
    """Получение списка всех торговых инструментов"""
    try:
        return db.get_all_instruments()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/public/orderbook/{ticker}", response_model=L2OrderBook, tags=["public"])
async def get_orderbook(ticker: str, limit: int = Query(default=10, le=25)):
    """Получение стакана заявок по инструменту"""
    try:
        if not ticker.strip():
            raise HTTPException(status_code=400, detail="Ticker cannot be empty")
            
        if not ticker.isalnum():
            raise HTTPException(status_code=400, detail="Ticker must contain only letters and numbers")
            
        if not db.get_instrument(ticker):
            raise HTTPException(status_code=404, detail="Instrument not found")
            
        return db.get_orderbook(ticker, limit)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/public/transactions/{ticker}", tags=["public"])
async def get_transactions(ticker: str):
    """Получение истории сделок по инструменту"""
    try:
        if not ticker.strip():
            raise HTTPException(status_code=400, detail="Ticker cannot be empty")
            
        if not ticker.isalnum():
            raise HTTPException(status_code=400, detail="Ticker must contain only letters and numbers")
            
        if not db.get_instrument(ticker):
            raise HTTPException(status_code=404, detail="Instrument not found")
            
        return db.get_transactions(ticker)
    except HTTPException:
        raise
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
            "name": "Authorization",
            "description": "Format: TOKEN {token}"
        }
    }
    # По умолчанию требовать ключ для всех эндпоинтов (можно убрать, если не нужно)
    for path in openapi_schema["paths"].values():
        for method in path.values():
            method.setdefault("security", [{"ApiKeyAuth": []}])
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

@app.delete("/api/v1/order/{order_id}", tags=["order"])
async def cancel_order(order_id: uuid.UUID, current_user: User = Depends(get_current_user)):
    """Отмена заявки пользователя"""
    try:
        order = db.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        # Здесь предполагается, что отмена меняет статус заявки на CANCELLED
        db.cancel_order(order_id)
        return Ok()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
