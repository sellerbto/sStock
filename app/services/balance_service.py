from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import Dict
from uuid import UUID
from app.models.balance import Balance
from app.models.instrument import Instrument
from app.services import user_service, instrument_service
import logging

async def get_user_balances(db: Session, user_id: UUID) -> Dict[str, int]:
    """Получение балансов пользователя"""
    # Проверяем существование пользователя
    await user_service.get_user(db, user_id)
    
    balances = db.query(Balance).filter(Balance.user_id == user_id).all()
    return {balance.ticker: balance.amount for balance in balances}

async def check_balance(db: Session, user_id: UUID, ticker: str, amount: int) -> bool:
    """Проверка достаточности средств"""
    balance = db.query(Balance).filter(
        Balance.user_id == user_id,
        Balance.ticker == ticker
    ).first()
    
    return balance is not None and balance.amount >= amount

async def _get_instrument_for_balance(db: Session, ticker: str):
    """Внутренняя функция для проверки существования инструмента при работе с балансом.
    Проверяет только существование инструмента, игнорируя флаг is_active."""
    instrument = db.query(Instrument).filter(
        Instrument.ticker == ticker
    ).first()
    
    if not instrument:
        raise HTTPException(status_code=404, detail="Инструмент не найден")
    
    return instrument

async def deposit(db: Session, user_id: UUID, ticker: str, amount: int):
    """Пополнение баланса"""
    logger = logging.getLogger(__name__)
    logger.info(f"[DEPOSIT] Starting deposit flow: user={user_id}, ticker={ticker}, amount={amount}")

    if amount <= 0:
        logger.error(f"[DEPOSIT] Invalid amount: {amount}")
        raise HTTPException(status_code=400, detail="Сумма должна быть положительной")
    
    # Проверяем существование пользователя и инструмента
    try:
        instrument = await _get_instrument_for_balance(db, ticker)
        logger.info(f"[DEPOSIT] Found instrument: ticker={instrument.ticker}, active={instrument.is_active}")
    except HTTPException as e:
        logger.error(f"[DEPOSIT] Failed to find instrument: ticker={ticker}")
        raise

    # Проверяем текущий баланс
    balance = db.query(Balance).filter(
        Balance.user_id == user_id,
        Balance.ticker == ticker
    ).first()
    
    if balance:
        logger.info(f"[DEPOSIT] Found instrument: ticker={ticker}, active={instrument.is_active}")
        balance.amount += amount
        logger.info(f"[DEPOSIT] Updated balance: from={balance.amount - amount} to={balance.amount}")
    else:
        logger.info(f"[DEPOSIT] Creating new balance record: ticker={ticker}, amount={amount}")
        balance = Balance(user_id=user_id, ticker=ticker, amount=amount)
        db.add(balance)
    
    try:
        logger.info("[DEPOSIT] Committing transaction...")
        db.commit()
        db.refresh(balance)
        logger.info(f"[DEPOSIT] Successfully deposited {amount} {ticker}. Final balance: {balance.amount}")
    except Exception as e:
        db.rollback()
        logger.error(f"[DEPOSIT] Failed to deposit: {str(e)}")
        raise HTTPException(status_code=400, detail="Ошибка при пополнении баланса")
    
    return {"success": True}

async def withdraw(db: Session, user_id: UUID, ticker: str, amount: int):
    """Списание с баланса"""
    logger = logging.getLogger(__name__)
    logger.info(f"[WITHDRAW] Starting withdraw flow: user={user_id}, ticker={ticker}, amount={amount}")

    if amount <= 0:
        logger.error(f"[WITHDRAW] Invalid amount: {amount}")
        raise HTTPException(status_code=400, detail="Сумма должна быть положительной")
    
    # Проверяем существование пользователя и инструмента
    try:
        instrument = await _get_instrument_for_balance(db, ticker)
        logger.info(f"[WITHDRAW] Found instrument: ticker={instrument.ticker}, active={instrument.is_active}")
    except HTTPException as e:
        logger.error(f"[WITHDRAW] Failed to find instrument: ticker={ticker}")
        raise
    
    balance = db.query(Balance).filter(
        Balance.user_id == user_id,
        Balance.ticker == ticker
    ).first()
    
    if not balance or balance.amount < amount:
        logger.error(f"[WITHDRAW] Insufficient funds: balance={balance.amount if balance else 0}, requested={amount}")
        raise HTTPException(status_code=400, detail="Недостаточно средств")
    
    logger.info(f"[WITHDRAW] Current balance: {balance.amount}")
    balance.amount -= amount
    logger.info(f"[WITHDRAW] Updated balance: from={balance.amount + amount} to={balance.amount}")
    
    try:
        logger.info("[WITHDRAW] Committing transaction...")
        db.commit()
        db.refresh(balance)
        logger.info(f"[WITHDRAW] Successfully withdrawn {amount} {ticker}. Final balance: {balance.amount}")
    except Exception as e:
        db.rollback()
        logger.error(f"[WITHDRAW] Failed to withdraw: {str(e)}")
        raise HTTPException(status_code=400, detail="Ошибка при списании с баланса")
    
    return {"success": True} 