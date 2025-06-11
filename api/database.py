from sqlalchemy import create_engine, and_, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from contextlib import contextmanager
from typing import Dict, Optional, List, Union
from .models import (
    UserModel, BalanceModel, OrderModel, ExecutionModel, InstrumentModel,
    User, Balance, MarketOrder, LimitOrder, MarketOrderBody, LimitOrderBody,
    OrderStatus, Direction, ExecutionDetails, OrderExecutionSummary,
    Instrument, L2OrderBook, Level, Base
)
from uuid import UUID
from datetime import UTC
import logging

logger = logging.getLogger(__name__)

class DatabaseError(Exception):
    pass

class DatabaseIntegrityError(DatabaseError):
    pass

class DatabaseNotFoundError(DatabaseError):
    pass

class InsufficientAvailableError(DatabaseError):
    """Raised when the user has the asset/cash, but it is fully or partly locked."""
    pass

class CancelError(DatabaseError):
    """Raised when the cancellation of an order fails."""
    pass

class Database:
    def __init__(self, connection_string: str):
        self.engine = create_engine(
              connection_string,
              pool_size=20,          # tune for workload
              max_overflow=40,
              pool_pre_ping=True,
              future=True,
          )
          # Keep ORM instances alive after commit – avoids reloads
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
          # You may want to move this into migrations in production
        Base.metadata.create_all(self.engine)

    @contextmanager
    def get_session(self):
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
        except InsufficientAvailableError:              # 👈 pass through unchanged
               session.rollback()
               raise
        except CancelError:
            session.rollback()
            raise
        except Exception as e:
            session.rollback()
            raise DatabaseError(f"Unexpected error: {e}")
        finally:
            session.close()

    def _lock_funds_session(self, session: Session, user_id: UUID, ticker: str, amount: int):
        bal = session.query(BalanceModel).with_for_update().filter(
            and_(BalanceModel.user_id == str(user_id), BalanceModel.ticker == ticker)
        ).first()
        if not bal:
            raise InsufficientAvailableError(f"No balance found for {ticker}")
        available = bal.amount - bal.locked_amount
        if available < amount:
            raise InsufficientAvailableError(
                f"Insufficient available {ticker}: {available} < {amount}"
            )
        bal.locked_amount += amount

    # --- User management ---

    def add_user(self, user: User) -> None:
        try:
            with self.get_session() as session:
                session.add(UserModel(
                    id=str(user.id),
                    name=user.name,
                    role=user.role,
                    api_key=user.api_key,
                ))
        except DatabaseIntegrityError:
            raise DatabaseIntegrityError(f"User {user.name} or api_key already exists")

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        try:
            with self.get_session() as session:
                db = session.query(UserModel).filter(UserModel.api_key == api_key).first()
                if not db:
                    return None
                return User(id=db.id, name=db.name, role=db.role, api_key=db.api_key)
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get user by api_key: {e}")

    def get_user_by_name(self, name: str) -> Optional[User]:
        try:
            with self.get_session() as session:
                db = session.query(UserModel).filter(UserModel.name == name).first()
                if not db:
                    return None
                return User(id=db.id, name=db.name, role=db.role, api_key=db.api_key)
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get user by name: {e}")

    def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        try:
            with self.get_session() as session:
                db = session.query(UserModel).filter(UserModel.id == str(user_id)).first()
                if not db:
                    return None
                return User(id=db.id, name=db.name, role=db.role, api_key=db.api_key)
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get user by id: {e}")

    def delete_user(self, user_id: UUID) -> None:
        try:
            with self.get_session() as session:
                cnt = session.query(UserModel).filter(UserModel.id == str(user_id)).delete()
                if cnt == 0:
                    raise DatabaseNotFoundError(f"User {user_id} not found")
        except DatabaseError as e:
            raise DatabaseError(f"Failed to delete user: {e}")

    def get_transactions(self, ticker: str) -> List[ExecutionDetails]:
            """
            Returns all executions for orders.
            """
            with self.get_session() as session:
                rows = (
                    session.query(ExecutionModel, OrderModel.direction)
                    .join(OrderModel, ExecutionModel.order_id == OrderModel.id)
                    .filter(OrderModel.ticker == ticker)
                    .all()
                )

            transactions: List[ExecutionDetails] = []
            for exec_rec, direction in rows:
                transactions.append(
                    ExecutionDetails(
                        execution_id=exec_rec.id,
                        timestamp=exec_rec.executed_at,
                        quantity=exec_rec.quantity,
                        price=exec_rec.price,
                        counterparty_order_id=exec_rec.counterparty_order_id
                    )
                )
            return transactions

    # --- Balance management ---

    def get_user_balance(self, user_id: UUID) -> Dict[str, int]:
        try:
            with self.get_session() as session:
                bals = session.query(BalanceModel)\
                    .filter(BalanceModel.user_id == str(user_id)).all()
                return {b.ticker: b.amount for b in bals} if bals else {}
        except Exception as e:
            raise DatabaseError(f"Failed to get user balance: {e}")

    def update_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        with self.get_session() as session:
            bal = session.query(BalanceModel).with_for_update().filter(and_(
                BalanceModel.user_id == str(user_id),
                BalanceModel.ticker == ticker
            )).first()
            if not bal:
                bal = BalanceModel(user_id=str(user_id), ticker=ticker, amount=0, locked_amount=0)
                session.add(bal)
            new_amt = bal.amount + amount
            if new_amt < 0:
                raise ValueError(f"Insufficient balance for {ticker}: {bal.amount} < {abs(amount)}")
            bal.amount = new_amt

    def lock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        with self.get_session() as session:
            self._lock_funds_session(session, user_id, ticker, amount)

    def unlock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        with self.get_session() as session:
            bal = session.query(BalanceModel).with_for_update().filter(and_(
                BalanceModel.user_id == str(user_id),
                BalanceModel.ticker == ticker
            )).first()

            bal.locked_amount -= amount

    # --- Instrument management ---

    def add_instrument(self, instrument: Instrument) -> None:
        try:
            with self.get_session() as session:
                session.add(InstrumentModel(
                    ticker=instrument.ticker.upper(),
                    name=instrument.name.strip(),
                    is_active=True
                ))
        except DatabaseIntegrityError:
            raise DatabaseIntegrityError(f"Instrument {instrument.ticker} already exists")

    def get_instrument(self, ticker: str) -> Optional[Instrument]:
        try:
            with self.get_session() as session:
                db = session.query(InstrumentModel).filter(and_(
                    InstrumentModel.ticker == ticker.upper(),
                    InstrumentModel.is_active == True
                )).first()
                return Instrument(ticker=db.ticker, name=db.name) if db else None
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get instrument: {e}")

    def delete_instrument(self, ticker: str) -> None:
        try:
            with self.get_session() as session:
                cnt = session.query(InstrumentModel)\
                    .filter(InstrumentModel.ticker == ticker.upper()).delete()
                if cnt == 0:
                    raise DatabaseNotFoundError(f"Instrument {ticker} not found")
        except DatabaseError as e:
            raise DatabaseError(f"Failed to delete instrument: {e}")

    # --- Order placement & execution ---

    def add_market_order(self, order: MarketOrder) -> None:
        try:
            with self.get_session() as session:
                inst = session.query(InstrumentModel)\
                    .filter(InstrumentModel.ticker == order.body.ticker).first()
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
                    created_at=order.timestamp
                )
                session.add(db_o)
                session.flush()
                self.execute_market_order_internal(session, db_o)
        except Exception as e:
            raise DatabaseError(f"Failed to add market order: {e}")

    def add_limit_order(self, order: LimitOrder) -> None:
            """
            Place a new limit order, locking exactly what's needed up front
            in a single, well-ordered pass to avoid any inversion.
            """
            try:
                with self.get_session() as session:
                    inst = session.query(InstrumentModel)\
                                  .filter(InstrumentModel.ticker == order.body.ticker)\
                                  .first()
                    if not inst:
                        raise DatabaseNotFoundError(f"Instrument {order.body.ticker} not found")

                    ticker = order.body.ticker
                    qty    = order.body.qty
                    price  = order.body.price

                    # build list of (user_id, ticker, amount_to_lock)
                    locks: List[Tuple[UUID,str,int]] = []
                    if order.body.direction == Direction.SELL:
                        # seller must lock their asset
                        locks.append((order.user_id, ticker, qty))
                    else:
                        # buyer must lock their cash
                        locks.append((order.user_id, "RUB", qty * price))

                    # sort by (ticker, user_id) to define a single lock order
                    for uid, tk, amt in sorted(locks, key=lambda x: (x[1], str(x[0]))):
                        self._lock_funds_session(session, uid, tk, amt)

                    db_o = OrderModel(
                        id=order.id,
                        user_id=order.user_id,
                        ticker=ticker,
                        direction=order.body.direction,
                        quantity=qty,
                        price=price,
                        status=order.status,
                        created_at=order.timestamp
                    )
                    session.add(db_o)
                    session.flush()
                    self.execute_limit_order(session, db_o)

            except InsufficientAvailableError:
                raise  # handled by API layer

    def execute_market_order_internal(self, session: Session, order: OrderModel) -> None:
        filled = self.get_filled_quantity(session, order.id)
        to_fill = order.quantity - filled

        if order.direction == Direction.BUY:
            opp_q = session.query(OrderModel).filter(and_(
                OrderModel.ticker == order.ticker,
                OrderModel.direction == Direction.SELL,
                OrderModel.price.isnot(None),
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
            ))
            key = lambda o: (o.price, o.created_at)
        else:
            opp_q = session.query(OrderModel).filter(and_(
                OrderModel.ticker == order.ticker,
                OrderModel.direction == Direction.BUY,
                OrderModel.price.isnot(None),
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
            ))
            key = lambda o: (-o.price, o.created_at)

        candidates = [
            o for o in opp_q.with_for_update().all()
            if (o.quantity - self.get_filled_quantity(session, o.id)) > 0
        ]
        candidates.sort(key=key)

        for other in candidates:
            if to_fill <= 0:
                break
            rem = other.quantity - self.get_filled_quantity(session, other.id)
            qty = min(to_fill, rem)
            self._execute_orders(session, order, other, qty)
            to_fill -= qty

        final = self.get_filled_quantity(session, order.id)
        order.status = (
            OrderStatus.REJECTED if final == 0 else
            OrderStatus.PARTIALLY_EXECUTED if final < order.quantity else
            OrderStatus.EXECUTED
        )

    # NEW helper ---------------------------------------------------------------
    def _bulk_filled_qty(self, session: Session, order_ids: list[str]) -> dict[str, int]:
        """Return {order_id: already_filled_qty} for many orders in ONE query."""
        if not order_ids:
            return {}
        rows = (
            session.query(
                ExecutionModel.order_id,
                func.coalesce(func.sum(ExecutionModel.quantity), 0)
            )
            .filter(ExecutionModel.order_id.in_(order_ids))
            .group_by(ExecutionModel.order_id)
            .all()
        )
        return {oid: qty for oid, qty in rows}

    # REPLACE execute_limit_order ---------------------------------------------
    def execute_limit_order(self, session: Session, order: OrderModel) -> None:
        remaining_to_fill = order.quantity - self.get_filled_quantity(session, order.id)

        # Build single DB query that already orders by most attractive price
        if order.direction == Direction.BUY:           # we want cheapest asks first
            opp_q = (
                session.query(OrderModel)
                .filter(
                    OrderModel.ticker == order.ticker,
                    OrderModel.direction == Direction.SELL,
                    OrderModel.price <= order.price,
                    OrderModel.status.in_([OrderStatus.NEW,
                                           OrderStatus.PARTIALLY_EXECUTED]),
                    OrderModel.id != order.id
                )
                .order_by(OrderModel.price.asc(), OrderModel.created_at.asc())
                .with_for_update(skip_locked=True)
            )
        else:                                          # we want highest bids first
            opp_q = (
                session.query(OrderModel)
                .filter(
                    OrderModel.ticker == order.ticker,
                    OrderModel.direction == Direction.BUY,
                    OrderModel.price >= order.price,
                    OrderModel.status.in_([OrderStatus.NEW,
                                           OrderStatus.PARTIALLY_EXECUTED]),
                    OrderModel.id != order.id
                )
                .order_by(OrderModel.price.desc(), OrderModel.created_at.asc())
                .with_for_update(skip_locked=True)
            )

        # Fetch once; pre-compute already-filled amounts for *all* candidates
        candidates: list[OrderModel] = opp_q.all()
        filled_map = self._bulk_filled_qty(
            session, [str(o.id) for o in candidates] + [str(order.id)]
        )

        for other in candidates:
            if remaining_to_fill <= 0:
                break

            other_remaining = other.quantity - filled_map.get(str(other.id), 0)
            if other_remaining <= 0:
                continue

            qty = other_remaining if other_remaining < remaining_to_fill else remaining_to_fill
            self._execute_orders(session, order, other, qty)

            # keep local counters in sync to avoid further DB calls
            filled_map[str(other.id)] = filled_map.get(str(other.id), 0) + qty
            remaining_to_fill -= qty

        # Final status (unchanged logic)
        already_filled = order.quantity - remaining_to_fill
        order.status = (
            OrderStatus.NEW if already_filled == 0 else
            OrderStatus.PARTIALLY_EXECUTED if already_filled < order.quantity else
            OrderStatus.EXECUTED
        )


    def _execute_orders(self, session: Session,
                        order1: OrderModel, order2: OrderModel, qty: int) -> None:
        price = order2.price
        buyer, seller = (
            (order1, order2) if order1.direction == Direction.BUY else (order2, order1)
        )

        session.add(ExecutionModel(
            order_id=order1.id,
            counterparty_order_id=order2.id,
            quantity=qty,
            price=price
        ))

        self._update_balances(session,
                              buyer_id=UUID(buyer.user_id) if isinstance(buyer.user_id, str) else buyer.user_id,
                              seller_id=UUID(seller.user_id) if isinstance(seller.user_id, str) else seller.user_id,
                              ticker=order1.ticker,
                              qty=qty,
                              price=price)

        for o in (order1, order2):
            filled = self.get_filled_quantity(session, o.id)
            o.status = (
                OrderStatus.EXECUTED if filled >= o.quantity else
                OrderStatus.PARTIALLY_EXECUTED
            )

    def _update_balances(self,
                             session: Session,
                             buyer_id: UUID, seller_id: UUID,
                             ticker: str, qty: int, price: int) -> None:
            """
            Apply the four balance updates (buyer pays, seller receives, etc.)
            in a single pass, ordered by (ticker, user_id) to avoid deadlocks.
            """
            cost = qty * price

            # (user_id, ticker, Δamount, Δlocked)
            updates = [
                (buyer_id,  "RUB",    -cost,    -cost),  # buyer pays cash
                (seller_id, "RUB",     cost,      0),    # seller gets cash
                (buyer_id,  ticker,   +qty,      0),    # buyer gets asset
                (seller_id, ticker,   -qty,     -qty),  # seller releases asset
            ]

            # sort by ticker first, then by user_id string
            for uid, tk, d_amt, d_locked in sorted(updates, key=lambda x: (x[1], str(x[0]))):
                bal = session.query(BalanceModel)\
                             .with_for_update()\
                             .filter(
                                 BalanceModel.user_id == str(uid),
                                 BalanceModel.ticker  == tk
                             ).first()
                if not bal:
                    bal = BalanceModel(
                        user_id=str(uid),
                        ticker=tk,
                        amount=0,
                        locked_amount=0
                    )
                    session.add(bal)

                bal.amount        += d_amt
                bal.locked_amount += d_locked

    def get_filled_quantity(self, session: Session, order_id: Union[UUID, str]) -> int:
        key = order_id if isinstance(order_id, UUID) else UUID(order_id)
        return session.query(func.sum(ExecutionModel.quantity))\
            .filter(ExecutionModel.order_id == key).scalar() or 0

    # --- Cancellation ---

    def cancel_order(self, order_id: UUID) -> None:
        with self.get_session() as session:
            o = session.query(OrderModel).filter(OrderModel.id == str(order_id)).first()
            if not o:
                raise DatabaseNotFoundError(f"Order {order_id} not found")
            if o.price is None:
                raise CancelError("Cannot cancel a market order")
            if o.status != OrderStatus.NEW:
                raise CancelError(f"Cannot cancel order in status {o.status}")

            unfilled = o.quantity - self.get_filled_quantity(session, str(order_id))
            if unfilled > 0:
                if o.direction == Direction.SELL:
                    bal = session.query(BalanceModel).with_for_update().filter(and_(
                        BalanceModel.user_id == o.user_id,
                        BalanceModel.ticker == o.ticker
                    )).first()
                    if bal:
                        bal.locked_amount -= unfilled
                else:
                    bal = session.query(BalanceModel).with_for_update().filter(and_(
                        BalanceModel.user_id == o.user_id,
                        BalanceModel.ticker == "RUB"
                    )).first()
                    if bal:
                        bal.locked_amount -= unfilled * o.price

            o.status = OrderStatus.CANCELLED

    # --- Order retrieval & summaries ---

    def get_order(self, order_id: UUID) -> Optional[Union[MarketOrder, LimitOrder]]:
        with self.get_session() as session:
            db_o = session.query(OrderModel).filter(OrderModel.id == str(order_id)).first()
            if not db_o:
                return None
            filled = self.get_filled_quantity(session, db_o.id)
            if db_o.price is None:
                return MarketOrder(
                    id=db_o.id, status=db_o.status, user_id=db_o.user_id,
                    timestamp=db_o.created_at.replace(tzinfo=UTC),
                    body=MarketOrderBody(direction=db_o.direction, ticker=db_o.ticker, qty=db_o.quantity),
                    filled=filled
                )
            return LimitOrder(
                id=db_o.id, status=db_o.status, user_id=db_o.user_id,
                timestamp=db_o.created_at.replace(tzinfo=UTC),
                body=LimitOrderBody(direction=db_o.direction, ticker=db_o.ticker, qty=db_o.quantity, price=db_o.price),
                filled=filled
            )

    def get_user_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        with self.get_session() as session:
            db_orders = session.query(OrderModel)\
                .filter(OrderModel.user_id == str(user_id))\
                .order_by(OrderModel.created_at.desc()).all()
            result = []
            for o in db_orders:
                filled = self.get_filled_quantity(session, o.id)
                if o.price is None:
                    result.append(MarketOrder(
                        id=o.id, status=o.status, user_id=o.user_id,
                        timestamp=o.created_at.replace(tzinfo=UTC),
                        body=MarketOrderBody(direction=o.direction, ticker=o.ticker, qty=o.quantity),
                        filled=filled
                    ))
                else:
                    result.append(LimitOrder(
                        id=o.id, status=o.status, user_id=o.user_id,
                        timestamp=o.created_at.replace(tzinfo=UTC),
                        body=LimitOrderBody(direction=o.direction, ticker=o.ticker, qty=o.quantity, price=o.price),
                        filled=filled
                    ))
            return result

    def get_active_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        with self.get_session() as session:
            db_orders = session.query(OrderModel).filter(and_(
                OrderModel.user_id == str(user_id),
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
            )).all()
            result = []
            for o in db_orders:
                filled = self.get_filled_quantity(session, o.id)
                if o.price is None:
                    result.append(MarketOrder(
                        id=o.id, status=o.status, user_id=o.user_id,
                        timestamp=o.created_at.replace(tzinfo=UTC),
                        body=MarketOrderBody(direction=o.direction, ticker=o.ticker, qty=o.quantity),
                        filled=filled
                    ))
                else:
                    result.append(LimitOrder(
                        id=o.id, status=o.status, user_id=o.user_id,
                        timestamp=o.created_at.replace(tzinfo=UTC),
                        body=LimitOrderBody(direction=o.direction, ticker=o.ticker, qty=o.quantity, price=o.price),
                        filled=filled
                    ))
            return result

    def get_order_executions(self, order_id: UUID) -> List[ExecutionDetails]:
        with self.get_session() as session:
            execs = session.query(ExecutionModel).filter(
                ExecutionModel.order_id == str(order_id)
            ).all()
            return [
                ExecutionDetails(
                    execution_id=e.id,
                    timestamp=e.executed_at,
                    quantity=e.quantity,
                    price=e.price,
                    counterparty_order_id=e.counterparty_order_id
                ) for e in execs
            ]

    def get_order_execution_summary(self, order_id: UUID) -> Optional[OrderExecutionSummary]:
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
            executions=execs
        )

    def get_orderbook(self, ticker: str, limit: int = 10) -> L2OrderBook:
        with self.get_session() as session:
            active = session.query(OrderModel).filter(and_(
                OrderModel.ticker == ticker,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                OrderModel.price.isnot(None)
            )).all()

            bids = [o for o in active if o.direction == Direction.BUY]
            asks = [o for o in active if o.direction == Direction.SELL]

            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price)

            bid_levels = {}
            ask_levels = {}

            for o in bids:
                rem = o.quantity - self.get_filled_quantity(session, o.id)
                if rem > 0:
                    bid_levels[o.price] = bid_levels.get(o.price, 0) + rem

            for o in asks:
                rem = o.quantity - self.get_filled_quantity(session, o.id)
                if rem > 0:
                    ask_levels[o.price] = ask_levels.get(o.price, 0) + rem

            bid_list = [Level(price=p, qty=q) for p, q in bid_levels.items()][:limit]
            ask_list = [Level(price=p, qty=q) for p, q in ask_levels.items()][:limit]

            return L2OrderBook(bid_levels=bid_list, ask_levels=ask_list)

    def deposit_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        self.update_balance(user_id, ticker, amount)

    def withdraw_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        self.update_balance(user_id, ticker, -amount)

    def get_active_orders_by_ticker(self, ticker: str) -> List[OrderModel]:
        with self.get_session() as session:
            return session.query(OrderModel).filter(and_(
                OrderModel.ticker == ticker,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
            )).all()

    def get_all_instruments(self) -> List[Instrument]:
        try:
            with self.get_session() as session:
                insts = session.query(InstrumentModel).filter(InstrumentModel.is_active == True).all()
                return [Instrument(ticker=i.ticker, name=i.name) for i in insts]
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get instruments: {e}")

    def get_best_price(self, ticker: str, direction: Direction) -> Optional[int]:
        try:
            with self.get_session() as session:
                if direction == Direction.BUY:
                    o = session.query(OrderModel).filter(and_(
                        OrderModel.ticker == ticker,
                        OrderModel.direction == Direction.SELL,
                        OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                        OrderModel.price.isnot(None)
                    )).order_by(OrderModel.price.asc()).first()
                else:
                    o = session.query(OrderModel).filter(and_(
                        OrderModel.ticker == ticker,
                        OrderModel.direction == Direction.BUY,
                        OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                        OrderModel.price.isnot(None)
                    )).order_by(OrderModel.price.desc()).first()
                return o.price if o else None
        except Exception as e:
            raise DatabaseError(f"Failed to get best price: {e}")


# Global instance
db = Database("postgresql://postgres:postgres@db:5432/stock_exchange")
