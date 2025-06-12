from sqlalchemy import Column, String, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.models.base import Base
from app.schemas.user import UserRole

class User(Base):
    """Модель пользователя"""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.USER)
    api_key = Column(String, nullable=False, unique=True) 