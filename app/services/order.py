from datetime import datetime, timezone
from typing import Union
import logging

from app.models.order import Order as OrderModel
from app.schemas.order import (
    OrderStatus,
    Direction,
    LimitOrder,
    MarketOrder,
    LimitOrderBody,
    MarketOrderBody,
)

def convert_order_to_schema(order: OrderModel) -> Union[LimitOrder, MarketOrder]:
    """Конвертирует модель ордера в схему"""
    logger = logging.getLogger(__name__)
    
    # Проверяем, что timestamp существует
    if order.timestamp is None:
        logger.error(f"Order {order.id} has no timestamp!")
        # Используем текущее время как fallback
        timestamp = datetime.now(timezone.utc)
    else:
        timestamp = order.timestamp

    # Убеждаемся, что timestamp имеет timezone
    if timestamp.tzinfo is None:
        logger.warning(f"Service: Timestamp without timezone detected for order {order.id}. Adding UTC timezone.")
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    # Конвертируем в ISO 8601 строку с timezone
    timestamp_str = timestamp.isoformat()
    
    # Убеждаемся, что timezone указан явно
    if not timestamp_str.endswith('Z') and '+' not in timestamp_str and '-' not in timestamp_str[10:]:
        timestamp_str += 'Z'

    # Создаем базовые поля, общие для обоих типов ордеров
    base_fields = {
        "id": order.id,
        "status": order.status,
        "user_id": order.user_id,
        "timestamp": timestamp_str,
        "filled": order.filled or 0
    }

    # Создаем тело ордера в зависимости от типа
    if order.price is not None:  # Это LimitOrder
        body = LimitOrderBody(
            direction=order.direction,
            ticker=order.ticker,
            qty=order.qty,
            price=order.price
        )
        return LimitOrder(**base_fields, body=body)
    else:  # Это MarketOrder
        body = MarketOrderBody(
            direction=order.direction,
            ticker=order.ticker,
            qty=order.qty
        )
        return MarketOrder(**base_fields, body=body)

# ... остальной код без изменений ... 