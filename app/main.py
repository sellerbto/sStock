from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.v1 import public, user, admin
from app.core.config import settings
from app.models.base import get_db
from app.models.instrument import Instrument
from app.schemas.instrument import Instrument as InstrumentSchema
from app.services import instrument_service

# Настройка логирования
logging.basicConfig(
    level=logging.INFO
)

logger = logging.getLogger(__name__)

async def init_base_instruments():
    """Инициализация базовых инструментов"""
    try:
        db: Session = next(get_db())
        logger.info("[INIT] Initializing base currency RUB")
        
        # Используем UPSERT для безопасного добавления/обновления
        db.execute(
            text("""
                INSERT INTO instruments (ticker, name, is_active)
                VALUES (:ticker, :name, :is_active)
                ON CONFLICT (ticker) DO UPDATE
                SET name = :name, is_active = :is_active
            """),
            {
                "ticker": "RUB",
                "name": "Российский рубль",
                "is_active": True
            }
        )
        db.commit()
        logger.info("[INIT] Base currency RUB initialized successfully")
    except Exception as e:
        logger.error(f"[INIT] Failed to initialize base currency RUB: {str(e)}")
        raise

app = FastAPI(
    title="Toy Exchange",
    version="0.1.0",
)

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения"""
    logger.info("[INIT] Starting application initialization")
    await init_base_instruments()
    logger.info("[INIT] Application initialization completed")

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене заменить на список разрешенных доменов
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(public.router, prefix="/api/v1/public", tags=["public"])
app.include_router(user.router, prefix="/api/v1", tags=["user"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"]) 