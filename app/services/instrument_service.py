from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.instrument import Instrument
from app.schemas.instrument import Instrument as InstrumentSchema
from typing import List
import logging

async def add_instrument(db: Session, instrument_data: InstrumentSchema):
    """Добавление нового инструмента"""
    logger = logging.getLogger(__name__)
    logger.info(f"[DB] Starting instrument creation: ticker={instrument_data.ticker}, name={instrument_data.name}")
    
    try:
        # Проверяем существование инструмента (активного или неактивного)
        existing_instrument = db.query(Instrument).filter(
            Instrument.ticker == instrument_data.ticker
        ).first()
        
        logger.info(f"[DB] Existing instrument check: found={existing_instrument is not None}, active={existing_instrument.is_active if existing_instrument else None}")
        
        if existing_instrument:
            if existing_instrument.is_active:
                logger.error(f"[DB] Instrument {instrument_data.ticker} already exists and is active")
                raise HTTPException(
                    status_code=400,
                    detail="Инструмент уже существует"
                )
            else:
                # Реактивируем существующий инструмент
                logger.info(f"[DB] Reactivating existing instrument: ticker={instrument_data.ticker}")
                existing_instrument.is_active = True
                existing_instrument.name = instrument_data.name  # Обновляем имя
                db.commit()
                db.refresh(existing_instrument)
                logger.info(f"[DB] Successfully reactivated instrument: ticker={instrument_data.ticker}")
                return {"success": True}
        
        # Создаем новый инструмент если не существует
        instrument = Instrument(
            name=instrument_data.name,
            ticker=instrument_data.ticker,
            is_active=True
        )
        db.add(instrument)
        logger.info(f"[DB] Committing new instrument: ticker={instrument_data.ticker}")
        db.commit()
        db.refresh(instrument)
        logger.info(f"[DB] Successfully created new instrument: ticker={instrument_data.ticker}")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[DB] Failed to add instrument: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Ошибка при добавлении инструмента: {str(e)}"
        )
    
    return {"success": True}

async def delete_instrument(db: Session, ticker: str):
    """Удаление инструмента"""
    instrument = db.query(Instrument).filter(Instrument.ticker == ticker).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Инструмент не найден")
    
    # Используем мягкое удаление
    instrument.is_active = False
    try:
        db.commit()
        db.refresh(instrument)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ошибка при удалении инструмента")
    
    return {"success": True}

async def get_instruments(db: Session) -> List[Instrument]:
    """Получение списка активных инструментов"""
    return db.query(Instrument).filter(Instrument.is_active == True).all()

async def get_instrument(db: Session, ticker: str) -> Instrument:
    """Получение инструмента по тикеру"""
    instrument = db.query(Instrument).filter(
        Instrument.ticker == ticker,
        Instrument.is_active == True
    ).first()
    
    if not instrument:
        raise HTTPException(status_code=404, detail="Инструмент не найден")
    
    return instrument