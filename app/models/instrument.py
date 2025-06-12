from sqlalchemy import Column, String, Boolean
from app.models.base import Base

class Instrument(Base):
    """Модель торгового инструмента"""
    __tablename__ = "instruments"

    ticker = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)  # Для мягкого удаления 