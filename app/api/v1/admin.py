from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.models.base import get_db
from app.core.security import verify_admin_key
from app.schemas.user import User
from app.schemas.instrument import Instrument
from app.schemas.balance import Body_deposit_api_v1_admin_balance_deposit_post, Body_withdraw_api_v1_admin_balance_withdraw_post
from app.services import user_service, instrument_service, balance_service
import logging

router = APIRouter()

@router.delete("/user/{user_id}", response_model=User)
async def delete_user(
    user_id: UUID,
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Удаление пользователя"""
    logger = logging.getLogger(__name__)
    logger.info(f"[VALIDATION] Received user deletion request: user_id={user_id}")
    return await user_service.delete_user(db, user_id)

@router.post("/instrument")
async def add_instrument(
    instrument: Instrument,
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Добавление нового инструмента"""
    logger = logging.getLogger(__name__)
    logger.info(f"[VALIDATION] Received instrument data: ticker={instrument.ticker}, name={instrument.name}")
    try:
        return await instrument_service.add_instrument(db, instrument)
    except HTTPException as e:
        logger.error(f"[VALIDATION] Failed to add instrument: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"[VALIDATION] Unexpected error: {str(e)}")
        raise

@router.delete("/instrument/{ticker}")
async def delete_instrument(
    ticker: str,
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Удаление инструмента"""
    logger = logging.getLogger(__name__)
    logger.info(f"[VALIDATION] Received instrument deletion request: ticker={ticker}")
    return await instrument_service.delete_instrument(db, ticker)

@router.post("/balance/deposit")
async def deposit(
    deposit_data: Body_deposit_api_v1_admin_balance_deposit_post,
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Пополнение баланса пользователя"""
    logger = logging.getLogger(__name__)
    logger.info(f"[VALIDATION] Received deposit data: user_id={deposit_data.user_id}, ticker={deposit_data.ticker}, amount={deposit_data.amount}")
    return await balance_service.deposit(
        db,
        user_id=deposit_data.user_id,
        ticker=deposit_data.ticker,
        amount=deposit_data.amount
    )

@router.post("/balance/withdraw")
async def withdraw(
    withdraw_data: Body_withdraw_api_v1_admin_balance_withdraw_post,
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Списание с баланса пользователя"""
    logger = logging.getLogger(__name__)
    logger.info(f"[VALIDATION] Received withdraw data: user_id={withdraw_data.user_id}, ticker={withdraw_data.ticker}, amount={withdraw_data.amount}")
    return await balance_service.withdraw(
        db,
        user_id=withdraw_data.user_id,
        ticker=withdraw_data.ticker,
        amount=withdraw_data.amount
    ) 