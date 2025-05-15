from fastapi import Request, HTTPException, Depends, Header
from typing import Optional
from .database import db
from .models import User, UserRole

async def get_current_user(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> User:
    """
    Получает текущего пользователя по X-API-Key.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="X-API-Key header is missing"
        )

    user = db.get_user_by_api_key(x_api_key)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )

    return user

async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Проверяет, что текущий пользователь имеет роль ADMIN.
    Используется для защиты админских эндпоинтов.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Not enough permissions. Admin role required"
        )
    return current_user 