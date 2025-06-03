from pydantic import BaseModel, UUID4, EmailStr
from typing import Optional, Dict, Union, List
from enum import Enum
import uuid
import bcrypt
from datetime import datetime
from sqlalchemy import Column, Integer, String, Enum as SQLEnum, ForeignKey, DateTime, Numeric, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

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

# SQLAlchemy models
class UserModel(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False)
    api_key = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    
    # Добавляем связь с балансами
    balances = relationship("BalanceModel", back_populates="user", cascade="all, delete-orphan")

class BalanceModel(Base):
    __tablename__ = "balances"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    ticker = Column(String, nullable=False)
    amount = Column(Numeric, nullable=False, default=0)
    locked_amount = Column(Numeric, nullable=False, default=0)
    
    # Добавляем связь с пользователем
    user = relationship("UserModel", back_populates="balances")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'ticker', name='uix_user_ticker'),
    )

class OrderModel(Base):
    __tablename__ = "orders"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    ticker = Column(String, nullable=False)
    direction = Column(SQLEnum(Direction), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric, nullable=True)  # None для рыночных заявок
    status = Column(SQLEnum(OrderStatus), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Связь с пользователем
    user = relationship("UserModel")
    
    # Связь с исполнениями (где эта заявка является основной)
    executions = relationship(
        "ExecutionModel",
        primaryjoin="OrderModel.id==ExecutionModel.order_id",
        cascade="all, delete-orphan"
    )
    
    # Связь с исполнениями (где эта заявка является контрагентской)
    counterparty_executions = relationship(
        "ExecutionModel",
        primaryjoin="OrderModel.id==ExecutionModel.counterparty_order_id"
    )

class ExecutionModel(Base):
    __tablename__ = "executions"
    
    id = Column(Integer, primary_key=True)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    counterparty_order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric, nullable=False)
    executed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Связь с основной заявкой
    order = relationship(
        "OrderModel",
        foreign_keys=[order_id]
    )
    
    # Связь с контрагентской заявкой
    counterparty_order = relationship(
        "OrderModel",
        foreign_keys=[counterparty_order_id]
    )

class InstrumentModel(Base):
    __tablename__ = "instruments"
    
    ticker = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow) 