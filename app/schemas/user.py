from enum import Enum
from pydantic import BaseModel, Field
from uuid import UUID

class UserRole(str, Enum):
    """Роли пользователей"""
    USER = "USER"
    ADMIN = "ADMIN"

class NewUser(BaseModel):
    """Схема для создания нового пользователя"""
    name: str = Field(..., min_length=3)

class User(BaseModel):
    """Схема пользователя"""
    id: UUID
    name: str
    role: UserRole
    api_key: str

    class Config:
        from_attributes = True 