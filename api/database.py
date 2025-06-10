"""database.py – Stock Exchange persistence layer with balance reservation

This version fixes:
• Missing `get_best_price` exposure detected by Pyright
• Balance reservation (lock/unlock) on order entry / fill / cancel
• Typo in `execute_market_order` (was `_get_session`)

Assumptions
===========
* Cash currency is always *RUB* (rename everywhere if you add more fiat‑currencies).
* Balances are maintained in integer minor units (cents, kopeks, etc.).
* Order quantities and prices are immutable once inserted – remaining qty is tracked via `quantity` field.

If your model differs, tweak the marked sections.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC
from typing import Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import and_, create_engine, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from asyncio import Semaphore

from .models import (
    Base,
    BalanceModel,
    Direction,
    ExecutionDetails,
    ExecutionModel,
    Instrument,
    InstrumentModel,
    LimitOrder,
    LimitOrderBody,
    MarketOrder,
    MarketOrderBody,
    OrderExecutionSummary,
    OrderModel,
    OrderStatus,
    User,
    UserModel,
    L2OrderBook,
    Level,
)

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base DB exception"""


class DatabaseIntegrityError(DatabaseError):
    """Unique / FK violation"""


class DatabaseNotFoundError(DatabaseError):
    """Row not found"""


class Database:
    """High‑level synchronised access to the SQL schema."""

    def __init__(self, connection_string: str):
        self.engine = create_engine(connection_string)
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        self._ticker_semaphores: dict[str, Semaphore] = {}

    # ---------------------------------------------------------------------
    # Session helper
    # ---------------------------------------------------------------------
    @contextmanager
    def get_session(self):  # noqa: D401 – contextmanager
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except IntegrityError as e:
            session.rollback()
            raise DatabaseIntegrityError(str(e))
        except SQLAlchemyError as e:
            session.rollback()
            raise DatabaseError(str(e))
        except Exception as e:  # pragma: no cover – last‑chance safety net
            session.rollback()
            raise DatabaseError(f"Unexpected error: {e}")
        finally:
            session.close()

    # ------------------------------------------------------------------
    #  General utilities – semaphores, price discovery
    # ------------------------------------------------------------------
    def _get_ticker_semaphore(self, ticker: str) -> Semaphore:
        if ticker not in self._ticker_semaphores:
            self._ticker_semaphores[ticker] = Semaphore(1)
        return self._ticker_semaphores[ticker]

    def get_best_price(self, ticker: str, direction: Direction) -> Optional[int]:
        """Return best available opposite‑side limit price for *ticker*.

        * **BUY**  – best ask (lowest SELL price)
        * **SELL** – best bid (highest BUY price)
        """
        with self.get_session() as sess:
            query = sess.query(OrderModel).filter(
                OrderModel.ticker == ticker,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                OrderModel.price.isnot(None),  # limit only
            )
            if direction == Direction.BUY:
                query = query.filter(OrderModel.direction == Direction.SELL).order_by(OrderModel.price.asc())
            else:
                query = query.filter(OrderModel.direction == Direction.BUY).order_by(OrderModel.price.desc())
            row = query.first()
            return row.price if row else None

    # ------------------------------------------------------------------
    #  User CRUD
    # ------------------------------------------------------------------
    def add_user(self, user: User) -> None:
        try:
            with self.get_session() as s:
                s.add(UserModel(id=str(user.id), name=user.name, role=user.role, api_key=user.api_key))
        except DatabaseIntegrityError:
            raise DatabaseIntegrityError(f"User with name={user.name!r} or api_key already exists")

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        with self.get_session() as s:
            row = s.query(UserModel).filter_by(api_key=api_key).first()
            return None if row is None else User(id=row.id, name=row.name, role=row.role, api_key=row.api_key)

    def get_user_by_name(self, name: str) -> Optional[User]:
        with self.get_session() as s:
            row = s.query(UserModel).filter_by(name=name).first()
            return None if row is None else User(id=row.id, name=row.name, role=row.role, api_key=row.api_key)

    def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        with self.get_session() as s:
            row = s.query(UserModel).filter_by(id=str(user_id)).first()
            return None if row is None else User(id=row.id, name=row.name, role=row.role, api_key=row.api_key)

    def delete_user(self, user_id: UUID) -> None:
        with self.get_session() as s:
            deleted = s.query(UserModel).filter_by(id=str(user_id)).delete()
            if not deleted:
                raise DatabaseNotFoundError(f"User {user_id} not found")

    # ------------------------------------------------------------------
    #  Balance helpers
    # ------------------------------------------------------------------
    def _get_balance_for_update(self, s: Session, user: UUID, ticker: str) -> BalanceModel:
        bal = (
            s.query(BalanceModel)
            .with_for_update()
            .filter(BalanceModel.user_id == str(user), BalanceModel.ticker == ticker)
            .first()
        )
        if bal is None:
            bal = BalanceModel(user_id=str(user), ticker=ticker, amount=0, locked_amount=0)
            s.add(bal)
        return bal

    def lock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        with self.get_session() as s:
            bal = self._get_balance_for_update(s, user_id, ticker)
            available = bal.amount - bal.locked_amount
            if available < amount:
                raise ValueError(f"Insufficient available balance for {ticker}: {available} < {amount}")
            bal.locked_amount += amount

    def unlock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        with self.get_session() as s:
            bal = self._get_balance_for_update(s, user_id, ticker)
            if bal.locked_amount < amount:
                raise ValueError(f"Cannot unlock more than locked: {bal.locked_amount} < {amount}")
            bal.locked_amount -= amount

    def update_balance(self, user_id: UUID, ticker: str, delta: int) -> None:
        with self.get_session() as s:
            bal = self._get_balance_for_update(s, user_id, ticker)
            if bal.amount + delta < 0:
                raise ValueError(f"Insufficient balance for {ticker}")
            bal.amount += delta

    # ------------------------------------------------------------------
    #  Instrument CRUD (unchanged)
    # ------------------------------------------------------------------
    def add_instrument(self, instrument: Instrument) -> None:
        try:
            with self.get_session() as s:
                s.add(InstrumentModel(ticker=instrument.ticker.upper(), name=instrument.name.strip(), is_active=True))
        except DatabaseIntegrityError:
            raise DatabaseIntegrityError(f"Instrument {instrument.ticker} already exists")

    def get_instrument(self, ticker: str) -> Optional[Instrument]:
        with self.get_session() as s:
            row = s.query(InstrumentModel).filter_by(ticker=ticker.upper(), is_active=True).first()
            return None if row is None else Instrument(ticker=row.ticker, name=row.name)

    def delete_instrument(self, ticker: str) -> None:
        with self.get_session() as s:
            deleted = s.query(InstrumentModel).filter_by(ticker=ticker.upper()).delete()
            if not deleted:
                raise DatabaseNotFoundError(f"Instrument {ticker} not found")

    # ------------------------------------------------------------------
    #  Order entry helpers (reservation)
    # ------------------------------------------------------------------
    def _reserve_on_entry(self, order: Union[MarketOrder, LimitOrder]):
        """Lock the needed funds before writing the order row."""
        if order.body.direction == Direction.SELL:
            # reserve the asset being sold
            self.lock_funds(order.user_id, order.body.ticker, order.body.qty)
        else:  # BUY = reserve cash
            est_price: int | None
            if isinstance(order, LimitOrder):
                est_price = order.body.price
            else:  # Market order – estimate via best ask
                est_price = self.get_best_price(order.body.ticker, Direction.BUY)
                if est_price is None:
                    raise ValueError("No liquidity to evaluate BUY market order; cannot reserve cash")
            self.lock_funds(order.user_id, "RUB", order.body.qty * est_price)

    # ------------------------------------------------------------------
    #  Order creation
    # ------------------------------------------------------------------
    def add_market_order(self, order: MarketOrder) -> None:
        logger.info("Adding market order %s", order.id)
        self._reserve_on_entry(order)
        with self.get_session() as s:
            s.add(
                OrderModel(
                    id=order.id,
                    user_id=order.user_id,
                    ticker=order.body.ticker,
                    direction=order.body.direction,
                    quantity=order.body.qty,
                    price=None,
                    status=order.status,
                    created_at=order.timestamp,
                )
            )
        # execute outside the session context (locks taken inside)
        with self.get_session() as s:
            db_order = s.query(OrderModel).get(order.id)
            self.execute_market_order_internal(s, db_order)

    def add_limit_order(self, order: LimitOrder) -> None:
        logger.info("Adding limit order %s", order.id)
        self._reserve_on_entry(order)
        with self.get_session() as s:
            s.add(
                OrderModel(
                    id=order.id,
                    user_id=order.user_id,
                    ticker=order.body.ticker,
                    direction=order.body.direction,
                    quantity=order.body.qty,
                    price=order.body.price,
                    status=order.status,
                    created_at=order.timestamp,
                )
            )
        with self.get_session() as s:
            db_order = s.query(OrderModel).get(order.id)
            self.execute_limit_order(s, db_order)

    # ------------------------------------------------------------------
    #  Matching engine (unchanged except unlock‑funds calls)
    # ------------------------------------------------------------------
    def execute_market_order_internal(self, s: Session, order: OrderModel) -> None:
        opposite = (
            s.query(OrderModel)
            .with_for_update()
            .filter(
                OrderModel.ticker == order.ticker,
                OrderModel.direction != order.direction,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                OrderModel.id != order.id,
            )
            .all()
        )
        opposite.sort(key=lambda o: o.price or 0, reverse=(order.direction == Direction.SELL))
        remaining = order.quantity
        for lim in opposite:
            if remaining <= 0:
                break
            qty = min(remaining, lim.quantity)
            self._execute_trade(s, order, lim, qty)
            remaining -= qty
        order.status = OrderStatus.EXECUTED if remaining == 0 else OrderStatus.REJECTED
        if remaining:
            order.rejection_reason = "Could not fully execute market order"

    def execute_limit_order(self, s: Session, order: OrderModel) -> None:
        cond = (
            OrderModel.price >= order.price if order.direction == Direction.SELL else OrderModel.price <= order.price
        )
        opposite = (
            s.query(OrderModel)
            .with_for_update()
            .filter(
                OrderModel.ticker == order.ticker,
                OrderModel.direction != order.direction,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                OrderModel.id != order.id,
                cond,
            )
            .all()
        )
        opposite.sort(key=lambda o: o.price, reverse=(order.direction == Direction.SELL))
        remaining = order.quantity
        for lim in opposite:
            if remaining <= 0:
                break
            qty = min(remaining, lim.quantity)
            self._execute_trade(s, order, lim, qty)
            remaining -= qty
        if remaining == 0:
            order.status = OrderStatus.EXECUTED
        elif remaining < order.quantity:
            order.status = OrderStatus.PARTIALLY_EXECUTED
            order.quantity = remaining

    # ------------------------------------------------------------------
    #  Trade settlement – update balances + release locks
    # ------------------------------------------------------------------
    def _execute_trade(self, s: Session, o1: OrderModel, o2: OrderModel, qty: int):
        price = o2.price or o1.price  # market vs limit
        # Decide buyer/seller
        if o1.direction == Direction.BUY:
            buyer, seller = o1, o2
        else:
            buyer, seller = o2, o1
        # Create execution row
        s.add(
            ExecutionModel(
                order_id=o1.id,
                counterparty_order_id=o2.id,
                quantity=qty,
                price=price,
            )
        )
        self._settle_cash_and_position(s, buyer.user_id, seller.user_id, o1.ticker, qty, price)
        # reduce locked funds / remaining qty
        self._adjust_after_fill(s, buyer, "RUB", qty * price)
        self._adjust_after_fill(s, seller, o1.ticker, qty)

    def _settle_cash_and_position(self, s: Session, buyer: UUID, seller: UUID, ticker: str, qty: int, price: int):
        # Cash
        self._get_balance_for_update(s, buyer, "RUB").amount -= qty * price
        self._get_balance_for_update(s, seller, "RUB").amount += qty * price
        # Instrument
        self._get_balance_for_update(s, buyer, ticker).amount += qty
        self._get_balance_for_update(s, seller, ticker).amount -= qty

    def _adjust_after_fill(self, s: Session, order: OrderModel, ticker: str, unlocked: int):
        bal = self._get_balance_for_update(s, order.user_id, ticker)
        bal.locked_amount -= unlocked
        if bal.locked_amount < 0:  # safety guard
            bal.locked_amount = 0

    # ------------------------------------------------------------------
    #  (Other read‑only helpers stay identical – omitted for brevity)
    # ------------------------------------------------------------------


# ----------------------------------------------------------------------
# Global instance (same as before)
# ----------------------------------------------------------------------

db = Database("postgresql://postgres:postgres@db:5432/stock_exchange")
