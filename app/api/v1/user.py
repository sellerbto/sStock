from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Union
from uuid import UUID
from app.models.base import get_db
from app.core.security import verify_api_key
from app.schemas.order import (
    LimitOrderBody, MarketOrderBody, CreateOrderResponse,
    LimitOrder, MarketOrder
)
from app.schemas.balance import BalanceResponse
from app.services import order_service, balance_service
import logging

router = APIRouter()

@router.get("/balance", response_model=Dict[str, int])
async def get_balances(
    user_id: UUID = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """Получение балансов пользователя"""
    return await balance_service.get_user_balances(db, user_id)

@router.post("/order", response_model=CreateOrderResponse)
async def create_order(
    order: Union[LimitOrderBody, MarketOrderBody],
    user_id: UUID = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """Создание ордера"""
    logger = logging.getLogger(__name__)
    
    logger.debug(f"Creating order. User ID: {user_id}")
    logger.debug(f"Order data: {order}")
    try:
        return await order_service.create_order(db, user_id, order)
    except HTTPException as e:
        logger.error(f"Failed to create order: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=400, detail="Ошибка при создании ордера")

@router.get("/order", response_model=List[Union[LimitOrder, MarketOrder]])
async def list_orders(
    user_id: UUID = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """Получение списка активных ордеров пользователя"""
    return await order_service.get_user_orders(db, user_id)

@router.get("/order/{order_id}", response_model=Union[LimitOrder, MarketOrder])
async def get_order(
    order_id: UUID,
    user_id: UUID = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """Получение информации об ордере"""
    return await order_service.get_order(db, order_id, user_id)

@router.delete("/order/{order_id}")
async def cancel_order(
    order_id: UUID,
    user_id: UUID = Depends(verify_api_key),
    db: Session = Depends(get_db)
):
    """Отмена ордера"""
    return await order_service.cancel_order(db, order_id, user_id)