from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID
from jose import JWTError, jwt
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from app.core.config import settings

# Настройка заголовка авторизации
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def create_api_key(user_id: UUID) -> str:
    """Создание API ключа для пользователя"""
    return f"key-{str(user_id)}"

def verify_api_key(api_key: str = Security(api_key_header)) -> UUID:
    """Проверка API ключа"""
    if not api_key:
        raise HTTPException(status_code=401, detail="API ключ не предоставлен")
    
    # Проверяем формат токена
    if not api_key.startswith("TOKEN "):
        raise HTTPException(status_code=401, detail="Неверный формат токена")
    
    api_key = api_key.replace("TOKEN ", "")
    
    # Проверяем, что это API ключ пользователя
    if not api_key.startswith("key-"):
        raise HTTPException(status_code=401, detail="Неверный формат API ключа")
    
    user_id_str = api_key.replace("key-", "")
    try:
        return UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Неверный формат UUID в API ключе")

def verify_admin_key(api_key: str = Security(api_key_header)) -> bool:
    """Проверка административного API ключа"""
    if not api_key:
        raise HTTPException(status_code=401, detail="API ключ не предоставлен")
    
    if not api_key.startswith("TOKEN "):
        raise HTTPException(status_code=401, detail="Неверный формат токена")
    
    api_key = api_key.replace("TOKEN ", "")
    
    if api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    
    return True 