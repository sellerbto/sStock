from pydantic import BaseModel, UUID4, EmailStr
from typing import Optional, Dict, Union
from enum import Enum
import uuid
import bcrypt

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
    def create(cls, name: str, password: str) -> "User":
        # Генерируем хеш пароля
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        return cls(
            id=uuid.uuid4(),
            name=name,
            role=UserRole.USER,
            api_key=f"key-{uuid.uuid4()}",
            password_hash=password_hash.decode('utf-8')
        )

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

class Balance(BaseModel):
    user_id: uuid.UUID
    balances: Dict[str, int] = {}  # ticker -> amount mapping 

class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, Enum):
    NEW = "NEW"
    EXECUTED = "EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCELLED = "CANCELLED"

class MarketOrderBody(BaseModel):
    direction: Direction
    ticker: str
    qty: int

class LimitOrderBody(BaseModel):
    direction: Direction
    ticker: str
    qty: int
    price: int

class MarketOrder(BaseModel):
    id: uuid.UUID
    status: OrderStatus
    user_id: uuid.UUID
    timestamp: str
    body: MarketOrderBody

class LimitOrder(BaseModel):
    id: uuid.UUID
    status: OrderStatus
    user_id: uuid.UUID
    timestamp: str
    body: LimitOrderBody
    filled: int = 0

class CreateOrderResponse(BaseModel):
    success: bool = True
    order_id: uuid.UUID 