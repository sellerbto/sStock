from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import List, Union, Dict, Optional
from datetime import datetime
from uuid import UUID
from app.models.order import Order as OrderModel
from app.models.transaction import Transaction
from app.schemas.order import (
    LimitOrder, MarketOrder, OrderStatus,
    Direction, CreateOrderResponse, LimitOrderBody, MarketOrderBody
)
from app.schemas.instrument import L2OrderBook, Level
from app.services import balance_service, instrument_service
from app.services.order import convert_order_to_schema
import logging

async def get_orders(db: Session, user_id: Optional[UUID] = None) -> List[Union[LimitOrder, MarketOrder]]:
    """Получение списка ордеров"""
    logger = logging.getLogger(__name__)
    logger.info(f"Getting orders for user {user_id if user_id else 'all'}")
    
    query = db.query(OrderModel)
    if user_id:
        query = query.filter(OrderModel.user_id == user_id)
    
    orders = query.all()
    return [convert_order_to_schema(order) for order in orders]

async def create_order(
    db: Session,
    user_id: UUID,
    order_data: Union[LimitOrderBody, MarketOrderBody]
) -> CreateOrderResponse:
    """Создание ордера"""
    logger = logging.getLogger(__name__)
    logger.debug(f"Creating order: direction={order_data.direction}, ticker={order_data.ticker}, qty={order_data.qty}")
    
    # Проверяем существование инструмента
    await instrument_service.get_instrument(db, order_data.ticker)
    
    # Проверяем баланс
    if order_data.direction == Direction.SELL:
        # Для продажи проверяем баланс продаваемого инструмента
        logger.debug(f"Checking balance for SELL order: {order_data.qty} {order_data.ticker}")
        has_balance = await balance_service.check_balance(
            db, user_id, order_data.ticker, order_data.qty
        )
        if not has_balance:
            logger.error(f"Insufficient {order_data.ticker} balance for SELL order")
            raise HTTPException(status_code=400, detail="Недостаточно средств")
    else:
        # Для покупки проверяем баланс RUB
        if isinstance(order_data, LimitOrderBody):
            required_amount = order_data.qty * order_data.price
            logger.debug(f"Checking RUB balance for BUY order: {required_amount} RUB (qty={order_data.qty}, price={order_data.price})")
            has_balance = await balance_service.check_balance(
                db, user_id, "RUB", required_amount
            )
            if not has_balance:
                logger.error(f"Insufficient RUB balance for BUY order. Required: {required_amount}")
                raise HTTPException(status_code=400, detail="Недостаточно средств в RUB")
    
    # Создаем ордер
    order = OrderModel(
        user_id=user_id,
        ticker=order_data.ticker,
        direction=order_data.direction,
        qty=order_data.qty,
        price=getattr(order_data, 'price', None)  # None для рыночных ордеров
    )
    
    db.add(order)
    try:
        db.commit()
        db.refresh(order)
        logger.debug(f"Successfully created order {order.id}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create order: {str(e)}")
        raise HTTPException(status_code=400, detail="Ошибка при создании ордера")
    
    # Пытаемся исполнить ордер
    await try_execute_order(db, order)
    
    return CreateOrderResponse(success=True, order_id=order.id)

async def cancel_order(db: Session, order_id: UUID, user_id: UUID):
    """Отмена ордера"""
    order = await get_order(db, order_id, user_id)
    
    if order.status != OrderStatus.NEW:
        raise HTTPException(status_code=400, detail="Ордер нельзя отменить")
    
    order.status = OrderStatus.CANCELLED
    try:
        db.commit()
        db.refresh(order)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ошибка при отмене ордера")
    
    return {"success": True}

async def get_order(db: Session, order_id: UUID, user_id: UUID) -> Union[LimitOrder, MarketOrder]:
    """Получение ордера"""
    logger = logging.getLogger(__name__)
    logger.info(f"[ORDER] Getting order: id={order_id}, user_id={user_id}")
    
    order = db.query(OrderModel).filter(OrderModel.id == order_id).first()
    if not order:
        logger.error(f"[ORDER] Order not found: id={order_id}")
        raise HTTPException(status_code=404, detail="Ордер не найден")
    
    if order.user_id != user_id:
        logger.error(f"[ORDER] Access denied: order_user_id={order.user_id}, request_user_id={user_id}")
        raise HTTPException(status_code=403, detail="Нет доступа к ордеру")
    
    try:
        result = convert_order_to_schema(order)
        logger.info(f"[ORDER] Successfully converted order to schema: id={order_id}, type={'limit' if order.price is not None else 'market'}")
        return result
    except Exception as e:
        logger.error(f"[ORDER] Failed to convert order to schema: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка при обработке ордера")

async def get_user_orders(db: Session, user_id: UUID) -> List[Union[LimitOrder, MarketOrder]]:
    """Получение списка активных ордеров пользователя"""
    logger = logging.getLogger(__name__)
    logger.info(f"[ORDER] Getting active orders for user: {user_id}")
    
    orders = db.query(OrderModel).filter(
        OrderModel.user_id == user_id,
        OrderModel.status == OrderStatus.NEW
    ).all()
    
    try:
        result = [convert_order_to_schema(order) for order in orders]
        logger.info(f"[ORDER] Found {len(result)} active orders for user {user_id}")
        return result
    except Exception as e:
        logger.error(f"[ORDER] Failed to convert orders to schema: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка при обработке ордеров")

async def get_orderbook(db: Session, ticker: str, limit: int = 10) -> L2OrderBook:
    """Получение стакана заявок"""
    # Проверяем существование инструмента
    await instrument_service.get_instrument(db, ticker)
    
    # Получаем активные ордера
    orders = db.query(OrderModel).filter(
        OrderModel.ticker == ticker,
        OrderModel.status == OrderStatus.NEW
    ).all()
    
    # Группируем ордера по цене
    bids: Dict[int, int] = {}  # price -> total_qty
    asks: Dict[int, int] = {}  # price -> total_qty
    
    for order in orders:
        if not order.price:  # Пропускаем рыночные ордера
            continue
            
        if order.direction == Direction.BUY:
            bids[order.price] = bids.get(order.price, 0) + (order.qty - order.filled)
        else:
            asks[order.price] = asks.get(order.price, 0) + (order.qty - order.filled)
    
    # Сортируем и ограничиваем количество уровней
    bid_levels = [
        Level(price=price, qty=qty)
        for price, qty in sorted(bids.items(), reverse=True)[:limit]
    ]
    
    ask_levels = [
        Level(price=price, qty=qty)
        for price, qty in sorted(asks.items())[:limit]
    ]
    
    return L2OrderBook(bid_levels=bid_levels, ask_levels=ask_levels)

async def get_transaction_history(
    db: Session,
    ticker: str,
    limit: int = 10
) -> List[Transaction]:
    """Получение истории сделок"""
    # Проверяем существование инструмента
    await instrument_service.get_instrument(db, ticker)
    
    return db.query(Transaction).filter(
        Transaction.ticker == ticker
    ).order_by(Transaction.timestamp.desc()).limit(limit).all()

async def try_execute_order(db: Session, order: OrderModel):
    """Попытка исполнения ордера"""
    if order.status != OrderStatus.NEW:
        return
    
    # Находим встречные ордера
    opposite_direction = Direction.SELL if order.direction == Direction.BUY else Direction.BUY
    
    query = db.query(OrderModel).filter(
        OrderModel.ticker == order.ticker,
        OrderModel.direction == opposite_direction,
        OrderModel.status == OrderStatus.NEW
    )
    
    if order.price:  # Для лимитных ордеров
        if order.direction == Direction.BUY:
            query = query.filter(OrderModel.price <= order.price)
        else:
            query = query.filter(OrderModel.price >= order.price)
        
        query = query.order_by(OrderModel.price)
    else:  # Для рыночных ордеров
        if order.direction == Direction.BUY:
            query = query.order_by(OrderModel.price)
        else:
            query = query.order_by(OrderModel.price.desc())
    
    opposite_orders = query.all()
    
    # Исполняем ордер
    remaining_qty = order.qty
    for opposite_order in opposite_orders:
        if remaining_qty == 0:
            break
            
        available_qty = opposite_order.qty - opposite_order.filled
        execute_qty = min(remaining_qty, available_qty)
        execute_price = opposite_order.price or order.price
        
        if not execute_price:
            continue
        
        # Создаем транзакцию
        transaction = Transaction(
            ticker=order.ticker,
            amount=execute_qty,
            price=execute_price,
            buyer_id=order.user_id if order.direction == Direction.BUY else opposite_order.user_id,
            seller_id=opposite_order.user_id if order.direction == Direction.BUY else order.user_id
        )
        
        # Обновляем балансы
        if order.direction == Direction.BUY:
            await balance_service.withdraw(db, order.user_id, "RUB", execute_qty * execute_price)
            await balance_service.deposit(db, order.user_id, order.ticker, execute_qty)
            await balance_service.deposit(db, opposite_order.user_id, "RUB", execute_qty * execute_price)
            await balance_service.withdraw(db, opposite_order.user_id, order.ticker, execute_qty)
        else:
            await balance_service.deposit(db, order.user_id, "RUB", execute_qty * execute_price)
            await balance_service.withdraw(db, order.user_id, order.ticker, execute_qty)
            await balance_service.withdraw(db, opposite_order.user_id, "RUB", execute_qty * execute_price)
            await balance_service.deposit(db, opposite_order.user_id, order.ticker, execute_qty)
        
        # Обновляем ордера
        order.filled += execute_qty
        opposite_order.filled += execute_qty
        
        if opposite_order.filled == opposite_order.qty:
            opposite_order.status = OrderStatus.EXECUTED
        else:
            opposite_order.status = OrderStatus.PARTIALLY_EXECUTED
        
        remaining_qty -= execute_qty
        
        db.add(transaction)
    
    if remaining_qty == 0:
        order.status = OrderStatus.EXECUTED
    elif order.filled > 0:
        order.status = OrderStatus.PARTIALLY_EXECUTED
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ошибка при исполнении ордера") 