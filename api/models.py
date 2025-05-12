from pydantic import BaseModel, UUID4, EmailStr
from typing import Optional, Dict, Union, List
from enum import Enum
import uuid
import bcrypt
from datetime import datetime

class UserRole(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"

class NewUser(BaseModel):
    name: str
    password: str

class LoginUser(BaseModel):
    name: str
    password: str

class User(BaseModel):
    id: UUID4
    name: str
    role: UserRole
    api_key: str
    password_hash: str

    @classmethod
    def create(cls, name: str, password: str, role: UserRole = UserRole.USER) -> "User":
        # Генерируем хеш пароля
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        return cls(
            id=uuid.uuid4(),
            name=name,
            role=role,
            api_key=f"key-{uuid.uuid4()}",
            password_hash=password_hash.decode('utf-8')
        )

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

class Balance(BaseModel):
    user_id: UUID4
    balances: Dict[str, int] = {}  # ticker -> amount mapping 

class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, Enum):
    NEW = "NEW"
    EXECUTED = "EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

class ExecutionDetails(BaseModel):
    """Детали исполнения заявки"""
    execution_id: UUID4
    timestamp: datetime
    quantity: int
    price: int
    counterparty_order_id: UUID4  # ID встречной заявки

class OrderExecutionSummary(BaseModel):
    """Сводка по исполнению заявки"""
    total_filled: int  # Общее количество исполненных единиц
    average_price: float  # Средняя цена исполнения
    last_execution_time: Optional[datetime]  # Время последнего исполнения
    executions: List[ExecutionDetails] = []  # Список всех исполнений

class MarketOrderBody(BaseModel):
    direction: Direction
    ticker: str
    qty: int

class LimitOrderBody(BaseModel):
    direction: Direction
    ticker: str
    qty: int
    price: int

class BaseOrder(BaseModel):
    """Базовая модель для всех типов заявок"""
    id: UUID4
    status: OrderStatus
    user_id: UUID4
    timestamp: datetime
    execution_summary: Optional[OrderExecutionSummary] = None
    rejection_reason: Optional[str] = None

class MarketOrder(BaseOrder):
    body: MarketOrderBody

class LimitOrder(BaseOrder):
    body: LimitOrderBody
    filled: int = 0  # Количество исполненных единиц

class CreateOrderResponse(BaseModel):
    order_id: UUID4
    success: bool = True
    status: Optional[OrderStatus] = None
    rejection_reason: Optional[str] = None

class Ok(BaseModel):
    success: bool = True

class Instrument(BaseModel):
    name: str
    ticker: str

class Level(BaseModel):
    price: int
    qty: int

class L2OrderBook(BaseModel):
    bid_levels: List[Level]
    ask_levels: List[Level]

class Transaction(BaseModel):
    ticker: str
    amount: int
    price: int
    timestamp: datetime

class DepositRequest(BaseModel):
    user_id: UUID4
    ticker: str
    amount: int

class WithdrawRequest(BaseModel):
    user_id: UUID4
    ticker: str
    amount: int 