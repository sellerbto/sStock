from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """Настройки приложения"""
    DATABASE_URL: str
    SECRET_KEY: str
    ADMIN_API_KEY: str
    
    # Настройки SSL/TLS
    SSL_KEYFILE: Optional[str] = None
    SSL_CERTFILE: Optional[str] = None
    
    class Config:
        env_file = ".env"

settings = Settings() 