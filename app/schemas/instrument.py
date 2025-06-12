from pydantic import BaseModel, Field

class Instrument(BaseModel):
    """Схема инструмента"""
    name: str
    ticker: str = Field(..., pattern="^[A-Z]{2,10}$")

    class Config:
        from_attributes = True

class Level(BaseModel):
    """Уровень в стакане"""
    price: int
    qty: int

class L2OrderBook(BaseModel):
    """Стакан заявок"""
    bid_levels: list[Level]
    ask_levels: list[Level] 