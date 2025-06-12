from sqlalchemy import Column, String, Integer, Enum as SQLEnum, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone
from app.schemas.order import OrderStatus, Direction
from app.models.base import Base
import logging

logger = logging.getLogger(__name__)

class Order(Base):
    """Модель ордера"""
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ticker = Column(String, ForeignKey("instruments.ticker"), nullable=False)
    direction = Column(SQLEnum(Direction), nullable=False)
    status = Column(SQLEnum(OrderStatus), nullable=False, default=OrderStatus.NEW)
    qty = Column(Integer, nullable=False)
    price = Column(Integer, nullable=True)  # null для market ордеров
    filled = Column(Integer, nullable=False, default=0)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __init__(self, **kwargs):
        if 'timestamp' in kwargs:
            ts = kwargs['timestamp']
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    logger.warning(f"DB: Timestamp without timezone detected for order creation. Adding UTC timezone.")
                    kwargs['timestamp'] = ts.replace(tzinfo=timezone.utc)
                elif ts.tzinfo != timezone.utc:
                    logger.info(f"DB: Converting timestamp to UTC for order creation")
                    kwargs['timestamp'] = ts.astimezone(timezone.utc)
        else:
            kwargs['timestamp'] = datetime.now(timezone.utc)
        
        super().__init__(**kwargs)
        logger.info(f"Created order: id={self.id}, direction={self.direction}, "
                   f"ticker={self.ticker}, qty={self.qty}, price={self.price}, "
                   f"timestamp={self.timestamp}")

    def __str__(self):
        return f"Order(id={self.id}, direction={self.direction}, ticker={self.ticker}, qty={self.qty}, price={self.price}, timestamp={self.timestamp})" 