from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.models.base import get_db
from app.core.security import create_api_key
from app.schemas.user import NewUser, User
from app.schemas.instrument import Instrument, L2OrderBook
from app.schemas.transaction import Transaction
from app.services import user_service, instrument_service, order_service

router = APIRouter()

@router.post("/register", response_model=User)
async def register(user_data: NewUser, db: Session = Depends(get_db)):
    """Регистрация нового пользователя"""
    return await user_service.create_user(db, user_data)

@router.get("/instrument", response_model=List[Instrument])
async def list_instruments(db: Session = Depends(get_db)):
    """Получение списка доступных инструментов"""
    return await instrument_service.get_instruments(db)

@router.get("/orderbook/{ticker}", response_model=L2OrderBook)
async def get_orderbook(ticker: str, limit: int = 10, db: Session = Depends(get_db)):
    """Получение стакана заявок"""
    return await order_service.get_orderbook(db, ticker, limit)

@router.get("/transactions/{ticker}", response_model=List[Transaction])
async def get_transaction_history(ticker: str, limit: int = 10, db: Session = Depends(get_db)):
    """Получение истории сделок"""
    return await order_service.get_transaction_history(db, ticker, limit) 