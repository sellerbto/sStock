from fastapi import Request, HTTPException, Depends, Header
from typing import Optional
from .database import db
from .models import User, UserRole

async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    """
    Получает текущего пользователя по токену из заголовка Authorization.
    Ожидает формат: Authorization: TOKEN {token}
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization header is missing"
        )

    try:
        # Проверяем формат заголовка
        auth_type, token = authorization.split(" ", 1)
        if auth_type != "TOKEN":
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization type. Expected: TOKEN"
            )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Expected: TOKEN {token}"
        )

    user = db.get_user_by_api_key(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
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