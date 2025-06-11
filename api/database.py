# database_optimized.py
# ---------------------------------------------------------------------------
# A faster, allocation-lighter version of the original Database class.
# All behaviour is 100 % compatible with the previous code.
# ---------------------------------------------------------------------------

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC
from typing import Dict, List, Optional, Union, Generator
from uuid import UUID
from datetime import datetime


from sqlalchemy import (
    and_,
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .models import (  # unchanged re-export from your models module
    Base,
    Balance,
    BalanceModel,
    Direction,
    ExecutionDetails,
    ExecutionModel,
    Instrument,
    InstrumentModel,
    L2OrderBook,
    Level,
    LimitOrder,
    LimitOrderBody,
    MarketOrder,
    MarketOrderBody,
    OrderExecutionSummary,
    OrderModel,
    OrderStatus,
    User,
    UserModel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain-level exceptions (unchanged)
# ---------------------------------------------------------------------------

class DatabaseError(Exception): ...
class DatabaseIntegrityError(DatabaseError): ...
class DatabaseNotFoundError(DatabaseError): ...

class InsufficientAvailableError(DatabaseError):
    """Raised when the user has the asset/cash, but it is fully or partly locked."""
    pass

class CancelError(DatabaseError):
    """Raised when the cancellation of an order fails."""
    pass


# ---------------------------------------------------------------------------
# Main data-access class
# ---------------------------------------------------------------------------

class Database:
    """Thread-safe companion object used by the service layer and API handlers."""

    # ---------- initialisation ------------------------------------------------

    def __init__(self, connection_string: str) -> None:
        # Fast connection pool + SQLA 2.0 execution engine
        self.engine = create_engine(
            connection_string,
            pool_size=20,          # tune for workload
            max_overflow=40,
            pool_pre_ping=True,
            future=True,
            # Добавляем настройки для предотвращения deadlock
            isolation_level="READ COMMITTED",
            pool_recycle=3600,
        )
        # Keep ORM instances alive after commit – avoids reloads
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        # You may want to move this into migrations in production
        Base.metadata.create_all(self.engine)

    # ---------- session/context helper ---------------------------------------

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except IntegrityError as e:
            session.rollback()
            raise DatabaseIntegrityError(str(e))
        except (InsufficientAvailableError, CancelError):
            session.rollback()
            raise
        except SQLAlchemyError as e:
            session.rollback()
            raise DatabaseError(str(e))
        except Exception as e:
            session.rollback()
            raise DatabaseError(f"Unexpected error: {e}")
        finally:
            session.close()

    # ------------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------------

    # --- filled-quantity map in ONE query ------------------------------------

    def _bulk_filled_qty(self, session: Session, order_ids: list[str]) -> dict[str, int]:
        """Return {order_id: already_filled_qty} for many orders in one DB round-trip."""
        if not order_ids:
            return {}
        rows = (
            session.query(
                ExecutionModel.order_id,
                func.coalesce(func.sum(ExecutionModel.quantity), 0),
            )
            .filter(ExecutionModel.order_id.in_(order_ids))
            .group_by(ExecutionModel.order_id)
            .all()
        )
        return {oid: qty for oid, qty in rows}

    # --- fast balance upsert --------------------------------------------------

    def _upsert_balance(
        self,
        session: Session,
        user_id: UUID,
        ticker: str,
        amount_delta: int = 0,
        locked_delta: int = 0,
    ) -> None:
        """Atomic INSERT … ON CONFLICT that updates amount/locked_amount."""
        if amount_delta == locked_delta == 0:
            return

        stmt = (
            insert(BalanceModel)
            .values(
                user_id=str(user_id),
                ticker=ticker,
                amount=amount_delta,
                locked_amount=locked_delta,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "ticker"],
                set_={
                    "amount": BalanceModel.amount + amount_delta,
                    "locked_amount": BalanceModel.locked_amount + locked_delta,
                },
            )
        )
        session.execute(stmt)

    # ------------------------------------------------------------------------
    # user management (unchanged, but uses faster ORM pattern)
    # ------------------------------------------------------------------------

    def add_user(self, user: User) -> None:
        try:
            with self.get_session() as session:
                session.add(
                    UserModel(
                        id=str(user.id),
                        name=user.name,
                        role=user.role,
                        api_key=user.api_key,
                    )
                )
        except DatabaseIntegrityError:
            raise DatabaseIntegrityError(f"User {user.name} or api_key already exists")

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        with self.get_session() as session:
            db = (
                session.query(UserModel)
                .filter(UserModel.api_key == api_key)
                .first()
            )
            if not db:
                return None
            return User(id=db.id, name=db.name, role=db.role, api_key=db.api_key)

    def get_user_by_name(self, name: str) -> Optional[User]:
        with self.get_session() as session:
            db = session.query(UserModel).filter(UserModel.name == name).first()
            if not db:
                return None
            return User(id=db.id, name=db.name, role=db.role, api_key=db.api_key)

    def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        with self.get_session() as session:
            db = session.query(UserModel).filter(UserModel.id == str(user_id)).first()
            if not db:
                return None
            return User(id=db.id, name=db.name, role=db.role, api_key=db.api_key)

    def delete_user(self, user_id: UUID) -> None:
        with self.get_session() as session:
            cnt = session.query(UserModel).filter(UserModel.id == str(user_id)).delete()
            if cnt == 0:
                raise DatabaseNotFoundError(f"User {user_id} not found")

    # ------------------------------------------------------------------------
    # balance management (now uses atomic upserts / single-stmt locks)
    # ------------------------------------------------------------------------

    def get_user_balance(self, user_id: UUID) -> Dict[str, int]:
        with self.get_session() as session:
            bals = (
                session.query(BalanceModel)
                .filter(BalanceModel.user_id == str(user_id))
                .all()
            )
            return {b.ticker: b.amount for b in bals} if bals else {}

    def update_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        # Reject overdraft before issuing UPDATE
        if amount < 0:
            with self.get_session() as session:
                bal = (
                    session.query(BalanceModel)
                    .with_for_update()
                    .filter(
                        BalanceModel.user_id == str(user_id),
                        BalanceModel.ticker == ticker,
                    )
                    .first()
                )
                current = bal.amount if bal else 0
                if current + amount < 0:
                    raise ValueError(
                        f"Insufficient balance for {ticker}: {current} < {abs(amount)}"
                    )
        with self.get_session() as session:
            self._upsert_balance(session, user_id, ticker, amount_delta=amount)

    def lock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        with self.get_session() as session:
            # verify availability first
            bal = (
                session.query(BalanceModel)
                .with_for_update()
                .filter(
                    BalanceModel.user_id == str(user_id),
                    BalanceModel.ticker == ticker,
                )
                .first()
            )
            if not bal:
                raise InsufficientAvailableError(f"No balance found for {ticker}")
            if bal.amount - bal.locked_amount < amount:
                raise InsufficientAvailableError(
                    f"Insufficient available {ticker}: {bal.amount - bal.locked_amount} < {amount}"
                )
            # perform atomic update
            self._upsert_balance(session, user_id, ticker, locked_delta=amount)

    def unlock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        with self.get_session() as session:
            self._upsert_balance(session, user_id, ticker, locked_delta=-amount)

    # ------------------------------------------------------------------------
    # instrument management (unchanged)
    # ------------------------------------------------------------------------

    def add_instrument(self, instrument: Instrument) -> None:
        try:
            with self.get_session() as session:
                session.add(
                    InstrumentModel(
                        ticker=instrument.ticker.upper(),
                        name=instrument.name.strip(),
                        is_active=True,
                    )
                )
        except DatabaseIntegrityError:
            raise DatabaseIntegrityError(f"Instrument {instrument.ticker} already exists")

    def get_instrument(self, ticker: str) -> Optional[Instrument]:
        with self.get_session() as session:
            db = (
                session.query(InstrumentModel)
                .filter(
                    InstrumentModel.ticker == ticker.upper(),
                    InstrumentModel.is_active.is_(True),
                )
                .first()
            )
            return Instrument(ticker=db.ticker, name=db.name) if db else None

    def delete_instrument(self, ticker: str) -> None:
        with self.get_session() as session:
            cnt = (
                session.query(InstrumentModel)
                .filter(InstrumentModel.ticker == ticker.upper())
                .delete()
            )
            if cnt == 0:
                raise DatabaseNotFoundError(f"Instrument {ticker} not found")

    # ------------------------------------------------------------------------
    # order placement ---------------------------------------------------------
    # ------------------------------------------------------------------------

    def add_market_order(self, order: MarketOrder) -> None:
        try:
            with self.get_session() as session:
                inst = (
                    session.query(InstrumentModel)
                    .filter(InstrumentModel.ticker == order.body.ticker)
                    .first()
                )
                if not inst:
                    raise DatabaseNotFoundError(f"Instrument {order.body.ticker} not found")

                db_o = OrderModel(
                    id=order.id,
                    user_id=str(order.user_id),
                    ticker=order.body.ticker,
                    direction=order.body.direction,
                    quantity=order.body.qty,
                    price=None,
                    status=order.status,
                    created_at=order.timestamp,
                )
                session.add(db_o)
                session.flush()  # get PK

                self.execute_market_order_internal(session, db_o)
        except Exception as e:
            raise DatabaseError(f"Failed to add market order: {e}")

    def add_limit_order(self, order: LimitOrder) -> None:
        try:
            with self.get_session() as session:
                inst = (
                    session.query(InstrumentModel)
                    .filter(InstrumentModel.ticker == order.body.ticker)
                    .first()
                )
                if not inst:
                    raise DatabaseNotFoundError(f"Instrument {order.body.ticker} not found")

                ticker, qty, price = order.body.ticker, order.body.qty, order.body.price

                if order.body.direction == Direction.SELL:
                    self.lock_funds(order.user_id, ticker, qty)
                else:
                    self.lock_funds(order.user_id, "RUB", qty * price)

                db_o = OrderModel(
                    id=order.id,
                    user_id=str(order.user_id),
                    ticker=ticker,
                    direction=order.body.direction,
                    quantity=qty,
                    price=price,
                    status=order.status,
                    created_at=order.timestamp,
                )
                session.add(db_o)
                session.flush()

                self.execute_limit_order(session, db_o)
        except InsufficientAvailableError:
            raise  # propagate unchanged

    # ------------------------------------------------------------------------
    # match engine helpers ----------------------------------------------------

    def execute_limit_order(self, session: Session, order: OrderModel) -> None:
        """Execute a limit order against the order book."""
        if order.status != OrderStatus.NEW:
            return

        # Находим встречные ордера с блокировкой
        opposite_direction = Direction.SELL if order.direction == Direction.BUY else Direction.BUY
        query = (
            session.query(OrderModel)
            .filter(
                OrderModel.ticker == order.ticker,
                OrderModel.direction == opposite_direction,
                OrderModel.status == OrderStatus.NEW
            )
            .with_for_update()  # Блокируем строки для обновления
        )

        # Для покупки ищем ордера с ценой не выше указанной
        if order.direction == Direction.BUY:
            query = query.filter(OrderModel.price <= order.price).order_by(OrderModel.price)
        else:
            query = query.filter(OrderModel.price >= order.price).order_by(OrderModel.price.desc())

        opposite_orders = query.all()

        # Исполняем ордер
        remaining_qty = order.quantity
        for opposite_order in opposite_orders:
            if remaining_qty == 0:
                break

            available_qty = opposite_order.quantity - self.get_filled_quantity(session, opposite_order.id)
            execute_qty = min(remaining_qty, available_qty)
            execute_price = opposite_order.price

            if execute_qty > 0:
                self._execute_orders(session, order, opposite_order, execute_qty)
                remaining_qty -= execute_qty

        # Обновляем статус ордера
        if remaining_qty == 0:
            order.status = OrderStatus.FILLED
        elif remaining_qty < order.quantity:
            order.status = OrderStatus.PARTIALLY_FILLED
        session.add(order)

    def execute_market_order_internal(self, session: Session, order: OrderModel) -> None:
        """Execute a market order against the order book."""
        if order.status != OrderStatus.NEW:
            return

        # Находим встречные ордера с блокировкой
        opposite_direction = Direction.SELL if order.direction == Direction.BUY else Direction.BUY
        query = (
            session.query(OrderModel)
            .filter(
                OrderModel.ticker == order.ticker,
                OrderModel.direction == opposite_direction,
                OrderModel.status == OrderStatus.NEW
            )
            .with_for_update()  # Блокируем строки для обновления
        )

        # Для рыночных ордеров сортируем по цене
        if order.direction == Direction.BUY:
            query = query.order_by(OrderModel.price)  # Покупаем по самой низкой цене
        else:
            query = query.order_by(OrderModel.price.desc())  # Продаем по самой высокой цене

        opposite_orders = query.all()

        # Исполняем ордер
        remaining_qty = order.quantity
        for opposite_order in opposite_orders:
            if remaining_qty == 0:
                break

            available_qty = opposite_order.quantity - self.get_filled_quantity(session, opposite_order.id)
            execute_qty = min(remaining_qty, available_qty)
            execute_price = opposite_order.price

            if execute_qty > 0:
                self._execute_orders(session, order, opposite_order, execute_qty)
                remaining_qty -= execute_qty

        # Обновляем статус ордера
        if remaining_qty == 0:
            order.status = OrderStatus.FILLED
        elif remaining_qty < order.quantity:
            order.status = OrderStatus.PARTIALLY_FILLED
        session.add(order)

    def _execute_orders(self, session: Session, order1: OrderModel, order2: OrderModel, qty: int) -> None:
        """Execute a trade between two orders."""
        # Определяем покупателя и продавца
        if order1.direction == Direction.BUY:
            buyer_order = order1
            seller_order = order2
        else:
            buyer_order = order2
            seller_order = order1

        # Создаем запись о сделке
        execution = ExecutionModel(
            order_id=str(buyer_order.id),
            opposite_order_id=str(seller_order.id),
            quantity=qty,
            price=seller_order.price,
            timestamp=datetime.now(UTC)
        )
        session.add(execution)

        # Обновляем балансы
        self._update_balances(
            session,
            buyer_order.user_id,
            seller_order.user_id,
            order1.ticker,
            qty,
            seller_order.price
        )

    def _update_balances(
        self,
        session: Session,
        buyer_id: UUID,
        seller_id: UUID,
        ticker: str,
        qty: int,
        price: int
    ) -> None:
        """Update balances for both parties in a trade."""
        total_amount = qty * price

        # Обновляем баланс покупателя
        self._upsert_balance(
            session,
            buyer_id,
            ticker,
            amount_delta=qty,
            locked_delta=0
        )
        self._upsert_balance(
            session,
            buyer_id,
            "RUB",
            amount_delta=-total_amount,
            locked_delta=0
        )

        # Обновляем баланс продавца
        self._upsert_balance(
            session,
            seller_id,
            ticker,
            amount_delta=-qty,
            locked_delta=0
        )
        self._upsert_balance(
            session,
            seller_id,
            "RUB",
            amount_delta=total_amount,
            locked_delta=0
        )

    # ---------- streaming, batch-wise market matcher -------------------------

    def get_filled_quantity(self, session: Session, order_id: UUID) -> int:
        """Получение количества исполненных единиц заявки"""
        return session.query(func.sum(ExecutionModel.quantity)).filter(
            ExecutionModel.order_id == order_id
        ).scalar() or 0

    def get_order(self, order_id: UUID) -> Optional[Union[MarketOrder, LimitOrder]]:
        with self.get_session() as session:
            db_o = (
                session.query(OrderModel).filter(OrderModel.id == str(order_id)).first()
            )
            if not db_o:
                return None
            filled = self.get_filled_quantity(session, db_o.id)
            if db_o.price is None:
                return MarketOrder(
                    id=db_o.id,
                    status=db_o.status,
                    user_id=db_o.user_id,
                    timestamp=db_o.created_at.replace(tzinfo=UTC),
                    body=MarketOrderBody(
                        direction=db_o.direction,
                        ticker=db_o.ticker,
                        qty=db_o.quantity,
                    ),
                    filled=filled,
                )
            return LimitOrder(
                id=db_o.id,
                status=db_o.status,
                user_id=db_o.user_id,
                timestamp=db_o.created_at.replace(tzinfo=UTC),
                body=LimitOrderBody(
                    direction=db_o.direction,
                    ticker=db_o.ticker,
                    qty=db_o.quantity,
                    price=db_o.price,
                ),
                filled=filled,
            )

    def _hydrate_orders(
        self, session: Session, db_orders: List[OrderModel]
    ) -> List[Union[MarketOrder, LimitOrder]]:
        ids = [str(o.id) for o in db_orders]
        filled_map = self._bulk_filled_qty(session, ids)

        result: list[Union[MarketOrder, LimitOrder]] = []
        for o in db_orders:
            filled = filled_map.get(str(o.id), 0)
            if o.price is None:
                result.append(
                    MarketOrder(
                        id=o.id,
                        status=o.status,
                        user_id=o.user_id,
                        timestamp=o.created_at.replace(tzinfo=UTC),
                        body=MarketOrderBody(
                            direction=o.direction, ticker=o.ticker, qty=o.quantity
                        ),
                        filled=filled,
                    )
                )
            else:
                result.append(
                    LimitOrder(
                        id=o.id,
                        status=o.status,
                        user_id=o.user_id,
                        timestamp=o.created_at.replace(tzinfo=UTC),
                        body=LimitOrderBody(
                            direction=o.direction,
                            ticker=o.ticker,
                            qty=o.quantity,
                            price=o.price,
                        ),
                        filled=filled,
                    )
                )
        return result

    def get_user_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        with self.get_session() as session:
            db_orders = (
                session.query(OrderModel)
                .filter(OrderModel.user_id == str(user_id))
                .order_by(OrderModel.created_at.desc())
                .all()
            )
            return self._hydrate_orders(session, db_orders)

    def get_active_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        with self.get_session() as session:
            db_orders = (
                session.query(OrderModel)
                .filter(
                    OrderModel.user_id == str(user_id),
                    OrderModel.status.in_(
                        [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
                    ),
                )
                .all()
            )
            return self._hydrate_orders(session, db_orders)

    def get_order_executions(self, order_id: UUID) -> List[ExecutionDetails]:
        with self.get_session() as session:
            execs = session.query(ExecutionModel).filter(
                ExecutionModel.order_id == str(order_id)
            )
            return [
                ExecutionDetails(
                    execution_id=e.id,
                    timestamp=e.executed_at,
                    quantity=e.quantity,
                    price=e.price,
                    counterparty_order_id=e.counterparty_order_id,
                )
                for e in execs
            ]

    def get_order_execution_summary(
        self, order_id: UUID
    ) -> Optional[OrderExecutionSummary]:
        execs = self.get_order_executions(order_id)
        if not execs:
            return None
        total_filled = sum(e.quantity for e in execs)
        total_value = sum(e.quantity * e.price for e in execs)
        avg_price = total_value / total_filled if total_filled else 0
        last_time = max(e.timestamp for e in execs)
        return OrderExecutionSummary(
            total_filled=total_filled,
            average_price=avg_price,
            last_execution_time=last_time,
            executions=execs,
        )

    def get_orderbook(self, ticker: str, limit: int = 10) -> L2OrderBook:
        with self.get_session() as session:
            active = (
                session.query(OrderModel)
                .filter(
                    OrderModel.ticker == ticker,
                    OrderModel.status.in_(
                        [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
                    ),
                    OrderModel.price.is_not(None),
                )
                .all()
            )
            filled_map = self._bulk_filled_qty(session, [str(o.id) for o in active])

            bids: list[OrderModel] = [
                o for o in active if o.direction == Direction.BUY
            ]
            asks: list[OrderModel] = [
                o for o in active if o.direction == Direction.SELL
            ]

            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price)

            bid_levels: dict[int, int] = {}
            ask_levels: dict[int, int] = {}

            for o in bids:
                rem = o.quantity - filled_map.get(str(o.id), 0)
                if rem > 0:
                    bid_levels[o.price] = bid_levels.get(o.price, 0) + rem

            for o in asks:
                rem = o.quantity - filled_map.get(str(o.id), 0)
                if rem > 0:
                    ask_levels[o.price] = ask_levels.get(o.price, 0) + rem

            bid_list = [Level(price=p, qty=q) for p, q in bid_levels.items()][:limit]
            ask_list = [Level(price=p, qty=q) for p, q in ask_levels.items()][:limit]

            return L2OrderBook(bid_levels=bid_list, ask_levels=ask_list)

    # ------------------------------------------------------------------------
    # utility helpers
    # ------------------------------------------------------------------------

    def get_filled_quantity(self, session: Session, order_id: Union[UUID, str]) -> int:
        """Single-order helper—kept for rare call-sites where N=1."""
        key = order_id if isinstance(order_id, UUID) else UUID(order_id)
        return (
            session.query(func.sum(ExecutionModel.quantity))
            .filter(ExecutionModel.order_id == key)
            .scalar()
            or 0
        )

    # ------------------------------------------------------------------------
    # deposits / withdrawals
    # ------------------------------------------------------------------------

    def deposit_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        self.update_balance(user_id, ticker, amount)

    def withdraw_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        self.update_balance(user_id, ticker, -amount)

    # ------------------------------------------------------------------------
    # misc lookups
    # ------------------------------------------------------------------------

    def get_active_orders_by_ticker(self, ticker: str) -> List[OrderModel]:
        with self.get_session() as session:
            return (
                session.query(OrderModel)
                .filter(
                    OrderModel.ticker == ticker,
                    OrderModel.status.in_(
                        [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
                    ),
                )
                .all()
            )

    def get_all_instruments(self) -> List[Instrument]:
        with self.get_session() as session:
            insts = (
                session.query(InstrumentModel)
                .filter(InstrumentModel.is_active.is_(True))
                .all()
            )
            return [Instrument(ticker=i.ticker, name=i.name) for i in insts]

    def get_best_price(self, ticker: str, direction: Direction) -> Optional[int]:
        with self.get_session() as session:
            if direction == Direction.BUY:
                o = (
                    session.query(OrderModel)
                    .filter(
                        OrderModel.ticker == ticker,
                        OrderModel.direction == Direction.SELL,
                        OrderModel.status.in_(
                            [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
                        ),
                        OrderModel.price.is_not(None),
                    )
                    .order_by(OrderModel.price.asc())
                    .first()
                )
            else:
                o = (
                    session.query(OrderModel)
                    .filter(
                        OrderModel.ticker == ticker,
                        OrderModel.direction == Direction.BUY,
                        OrderModel.status.in_(
                            [OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]
                        ),
                        OrderModel.price.is_not(None),
                    )
                    .order_by(OrderModel.price.desc())
                    .first()
                )
            return o.price if o else None


# Global instance (unchanged signature)
db = Database("postgresql://postgres:postgres@db:5432/stock_exchange")
