from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

class Direction(str, Enum):
    """Направление ордера"""
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, Enum):
    """Статус ордера"""
    NEW = "NEW"
    EXECUTED = "EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    CANCELLED = "CANCELLED"

class LimitOrderBody(BaseModel):
    """Тело запроса для создания лимитного ордера"""
    direction: Direction
    ticker: str
    qty: int = Field(..., gt=0)
    price: int = Field(..., gt=0)

class MarketOrderBody(BaseModel):
    """Тело запроса для создания рыночного ордера"""
    direction: Direction
    ticker: str
    qty: int = Field(..., gt=0)

class CreateOrderResponse(BaseModel):
    """Ответ на создание ордера"""
    success: bool = True
    order_id: UUID

class OrderBase(BaseModel):
    """Базовая схема ордера"""
    id: UUID
    status: OrderStatus
    user_id: UUID
    timestamp: str = Field(..., pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(([+-]\d{2}:\d{2})|Z)$')
    filled: int = 0

    class Config:
        from_attributes = True

class LimitOrder(OrderBase):
    """Схема лимитного ордера"""
    body: LimitOrderBody

class MarketOrder(OrderBase):
    """Схема рыночного ордера"""
    body: MarketOrderBody 