from sqlalchemy import create_engine, select, update, and_, or_, func
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from contextlib import contextmanager
from typing import Dict, Optional, List, Union, Tuple
from .models import (
    UserModel, BalanceModel, OrderModel, ExecutionModel, InstrumentModel,
    User, Balance, MarketOrder, LimitOrder, MarketOrderBody, LimitOrderBody,
    OrderStatus, Direction, ExecutionDetails, OrderExecutionSummary, Instrument, L2OrderBook, Level,
    Base, OrderType
)
from uuid import UUID, uuid4
from datetime import datetime, UTC
import logging

logger = logging.getLogger(__name__)

class DatabaseError(Exception):
    """Базовый класс для ошибок базы данных"""
    pass

class DatabaseIntegrityError(DatabaseError):
    """Ошибка целостности данных"""
    pass

class DatabaseNotFoundError(DatabaseError):
    """Ошибка - запись не найдена"""
    pass

class Database:
    def __init__(self, connection_string: str):
        self.engine = create_engine(connection_string)
        self.SessionLocal = sessionmaker(bind=self.engine)
        # Создаем все таблицы при инициализации
        Base.metadata.create_all(self.engine)
        
    @contextmanager
    def get_session(self):
        """Контекстный менеджер для работы с сессией"""
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
        except Exception as e:
            session.rollback()
            raise DatabaseError(f"Unexpected error: {str(e)}")
        finally:
            session.close()

    def add_user(self, user: User) -> None:
        """Добавление пользователя"""
        try:
            with self.get_session() as session:
                db_user = UserModel(
                    id=str(user.id),
                    name=user.name,
                    role=user.role,
                    api_key=user.api_key,
                )
                session.add(db_user)
        except DatabaseIntegrityError as e:
            raise DatabaseIntegrityError(f"User with name {user.name} or api_key {user.api_key} already exists")
        except DatabaseError as e:
            raise DatabaseError(f"Failed to add user: {str(e)}")

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        """Получение пользователя по API ключу"""
        try:
            with self.get_session() as session:
                db_user = session.query(UserModel).filter(UserModel.api_key == api_key).first()
                if not db_user:
                    return None
                return User(
                    id=db_user.id,
                    name=db_user.name,
                    role=db_user.role,
                    api_key=db_user.api_key,
                )
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get user by api_key: {str(e)}")

    def get_user_by_name(self, name: str) -> Optional[User]:
        """Получение пользователя по имени"""
        try:
            with self.get_session() as session:
                db_user = session.query(UserModel).filter(UserModel.name == name).first()
                if not db_user:
                    return None
                return User(
                    id=db_user.id,
                    name=db_user.name,
                    role=db_user.role,
                    api_key=db_user.api_key,
                )
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get user by name: {str(e)}")

    def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Получение пользователя по ID"""
        try:
            with self.get_session() as session:
                db_user = session.query(UserModel).filter(UserModel.id == str(user_id)).first()
                if not db_user:
                    return None
                return User(
                    id=db_user.id,
                    name=db_user.name,
                    role=db_user.role,
                    api_key=db_user.api_key,
                )
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get user by id: {str(e)}")

#                   id                  | name  | role  |                 api_key
# --------------------------------------+-------+-------+------------------------------------------
#  fb156fad-f405-4797-a2b8-906a3aba5bca | admin | ADMIN | key-81ce43a7-14fd-45de-9b99-82218228935a

#f
    def delete_user(self, user_id: UUID) -> None:
        """Удаление пользователя"""
        try:
            with self.get_session() as session:
                result = session.query(UserModel).filter(UserModel.id == str(user_id)).delete()
                if result == 0:
                    raise DatabaseNotFoundError(f"User {user_id} not found")
        except DatabaseError as e:
            raise DatabaseError(f"Failed to delete user: {str(e)}")

    def get_user_balance(self, user_id: UUID) -> Dict[str, int]:
        """Получение баланса пользователя"""
        try:
            logger.info(f"Getting balance for user: {user_id}")
            with self.get_session() as session:
                balance = session.query(BalanceModel).filter(BalanceModel.user_id == str(user_id)).first()
                if not balance:
                    logger.warning(f"No balance found for user: {user_id}")
                    return {}
                logger.info(f"Found balance: {balance.balances}")
                return balance.balances
        except Exception as e:
            logger.error(f"Error getting user balance: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get user balance: {str(e)}")

    def update_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        """Обновление баланса пользователя"""
        with self.get_session() as session:
            # Блокируем строку для обновления
            balance = session.query(BalanceModel).with_for_update().filter(
                and_(
                    BalanceModel.user_id == str(user_id),
                    BalanceModel.ticker == ticker
                )
            ).first()
            
            if not balance:
                balance = BalanceModel(
                    user_id=str(user_id),
                    ticker=ticker,
                    amount=0,
                    locked_amount=0
                )
                session.add(balance)
            
            new_amount = balance.amount + amount
            if new_amount < 0:
                raise ValueError(f"Insufficient balance for {ticker}: {balance.amount} < {abs(amount)}")
            
            balance.amount = new_amount

    def lock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        """Блокировка средств для ордера"""
        with self.get_session() as session:
            balance = session.query(BalanceModel).with_for_update().filter(
                and_(
                    BalanceModel.user_id == str(user_id),
                    BalanceModel.ticker == ticker
                )
            ).first()
            
            if not balance:
                raise ValueError(f"No balance found for {ticker}")
            
            available = balance.amount - balance.locked_amount
            if available < amount:
                raise ValueError(f"Insufficient available balance for {ticker}: {available} < {amount}")
            
            balance.locked_amount += amount

    def unlock_funds(self, user_id: UUID, ticker: str, amount: int) -> None:
        """Разблокировка средств"""
        with self.get_session() as session:
            balance = session.query(BalanceModel).with_for_update().filter(
                and_(
                    BalanceModel.user_id == str(user_id),
                    BalanceModel.ticker == ticker
                )
            ).first()
            
            if not balance:
                raise ValueError(f"No balance found for {ticker}")
            
            if balance.locked_amount < amount:
                raise ValueError(f"Cannot unlock more than locked: {balance.locked_amount} < {amount}")
            
            balance.locked_amount -= amount

    def add_instrument(self, instrument: Instrument) -> None:
        """Добавление инструмента"""
        try:
            with self.get_session() as session:
                db_instrument = InstrumentModel(
                    ticker=instrument.ticker.upper(),
                    name=instrument.name.strip(),
                    is_active=True
                )
                session.add(db_instrument)
        except DatabaseIntegrityError as e:
            raise DatabaseIntegrityError(f"Instrument with ticker {instrument.ticker} already exists")
        except DatabaseError as e:
            raise DatabaseError(f"Failed to add instrument: {str(e)}")

    def get_instrument(self, ticker: str) -> Optional[Instrument]:
        """Получение инструмента"""
        try:
            with self.get_session() as session:
                db_instrument = session.query(InstrumentModel).filter(
                    and_(
                        InstrumentModel.ticker == ticker.upper(),
                        InstrumentModel.is_active == True
                    )
                ).first()
                
                if not db_instrument:
                    return None
                    
                return Instrument(
                    ticker=db_instrument.ticker,
                    name=db_instrument.name
                )
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get instrument: {str(e)}")

    def delete_instrument(self, ticker: str) -> None:
        """Удаление инструмента"""
        try:
            with self.get_session() as session:
                logger.info(f"Attempting to delete instrument with ticker: {ticker.upper()}")
                result = session.query(InstrumentModel).filter(
                    InstrumentModel.ticker == ticker.upper()
                ).delete()
                logger.info(f"Delete result: {result}")
                
                if result == 0:
                    logger.warning(f"No instrument found with ticker: {ticker.upper()}")
                    raise DatabaseNotFoundError(f"Instrument with ticker {ticker} not found")
                
                session.commit()
                logger.info(f"Successfully deleted instrument with ticker: {ticker.upper()}")
        except DatabaseError as e:
            logger.error(f"Error deleting instrument: {str(e)}")
            raise DatabaseError(f"Failed to delete instrument: {str(e)}")

    def add_market_order(self, order: MarketOrder) -> None:
        """Добавление рыночной заявки"""
        with self.get_session() as session:
            db_order = OrderModel(
                id=order.id,
                user_id=str(order.user_id),
                ticker=order.body.ticker,
                direction=order.body.direction,
                quantity=order.body.qty,
                price=None,  # Для рыночных заявок цена не указывается
                status=order.status
            )
            session.add(db_order)
            # Сразу пытаемся исполнить рыночную заявку
            self.execute_market_order_internal(session, db_order)

    def add_limit_order(self, order: LimitOrder) -> None:
        """Добавление лимитной заявки"""
        with self.get_session() as session:
            db_order = OrderModel(
                id=order.id,
                user_id=str(order.user_id),
                ticker=order.body.ticker,
                direction=order.body.direction,
                quantity=order.body.qty,
                price=order.body.price,
                status=order.status
            )
            session.add(db_order)
            # Пытаемся исполнить лимитную заявку
            self.execute_limit_order(session, db_order)

    def execute_market_order(self, order: MarketOrder) -> None:
        """Исполнение рыночной заявки"""
        with self.get_session() as session:
            db_order = session.query(OrderModel).filter(OrderModel.id == order.id).first()
            if not db_order:
                raise DatabaseNotFoundError(f"Order {order.id} not found")
            self.execute_market_order_internal(session, db_order)

    def execute_market_order_internal(self, session: Session, order: OrderModel) -> None:
        """Внутренний метод исполнения рыночной заявки"""
        # Получаем все активные лимитные заявки в противоположном направлении
        limit_orders = session.query(OrderModel).filter(
            and_(
                OrderModel.ticker == order.ticker,
                OrderModel.direction != order.direction,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                OrderModel.id != order.id
            )
        ).order_by(
            OrderModel.price.desc() if order.direction == Direction.BUY else OrderModel.price.asc()
        ).with_for_update().all()

        remaining_qty = order.quantity
        for limit_order in limit_orders:
            if remaining_qty <= 0:
                break

            # Определяем количество для исполнения
            qty = min(remaining_qty, limit_order.quantity)
            
            # Исполняем заявки
            self._execute_orders(session, order, limit_order, qty)
            
            remaining_qty -= qty

        # Обновляем статус рыночной заявки
        if remaining_qty == 0:
            order.status = OrderStatus.EXECUTED
        else:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "Не удалось исполнить рыночную заявку полностью"

    def execute_limit_order(self, session: Session, order: OrderModel) -> None:
        """Исполнение лимитной заявки"""
        # Получаем все активные лимитные заявки в противоположном направлении
        limit_orders = session.query(OrderModel).filter(
            and_(
                OrderModel.ticker == order.ticker,
                OrderModel.direction != order.direction,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                OrderModel.id != order.id,
                OrderModel.price >= order.price if order.direction == Direction.SELL else OrderModel.price <= order.price
            )
        ).order_by(
            OrderModel.price.desc() if order.direction == Direction.BUY else OrderModel.price.asc()
        ).with_for_update().all()

        remaining_qty = order.quantity
        for limit_order in limit_orders:
            if remaining_qty <= 0:
                break

            # Определяем количество для исполнения
            qty = min(remaining_qty, limit_order.quantity)
            
            # Исполняем заявки
            self._execute_orders(session, order, limit_order, qty)
            
            remaining_qty -= qty

        # Обновляем статус лимитной заявки
        if remaining_qty == 0:
            order.status = OrderStatus.EXECUTED
        elif remaining_qty < order.quantity:
            order.status = OrderStatus.PARTIALLY_EXECUTED
            order.quantity = remaining_qty

    def _execute_orders(self, session: Session, order1: OrderModel, order2: OrderModel, qty: int) -> None:
        """Исполнение заявок между собой"""
        price = order2.price  # Используем цену лимитной заявки
        
        # Определяем покупателя и продавца
        if order1.direction == Direction.BUY:
            buyer, seller = order1, order2
        else:
            buyer, seller = order2, order1
            
        # Создаем детали исполнения
        execution = ExecutionModel(
            order_id=order1.id,
            counterparty_order_id=order2.id,
            quantity=qty,
            price=price
        )
        session.add(execution)
        
        # Обновляем балансы
        self._update_balances(session, buyer.user_id, seller.user_id, buyer.ticker, qty, price)

    def _update_balances(self, session: Session, buyer_id: UUID, seller_id: UUID, ticker: str, qty: int, price: int) -> None:
        """Обновление балансов после исполнения заявки"""
        # Списываем деньги у покупателя
        buyer_balance = session.query(BalanceModel).with_for_update().filter(
            and_(
                BalanceModel.user_id == buyer_id,
                BalanceModel.ticker == "USD"
            )
        ).first()
        
        if not buyer_balance:
            buyer_balance = BalanceModel(
                user_id=buyer_id,
                ticker="USD",
                amount=0,
                locked_amount=0
            )
            session.add(buyer_balance)
        
        buyer_balance.amount -= qty * price
        
        # Начисляем деньги продавцу
        seller_balance = session.query(BalanceModel).with_for_update().filter(
            and_(
                BalanceModel.user_id == seller_id,
                BalanceModel.ticker == "USD"
            )
        ).first()
        
        if not seller_balance:
            seller_balance = BalanceModel(
                user_id=seller_id,
                ticker="USD",
                amount=0,
                locked_amount=0
            )
            session.add(seller_balance)
        
        seller_balance.amount += qty * price
        
        # Обновляем балансы по инструменту
        buyer_instrument_balance = session.query(BalanceModel).with_for_update().filter(
            and_(
                BalanceModel.user_id == buyer_id,
                BalanceModel.ticker == ticker
            )
        ).first()
        
        if not buyer_instrument_balance:
            buyer_instrument_balance = BalanceModel(
                user_id=buyer_id,
                ticker=ticker,
                amount=0,
                locked_amount=0
            )
            session.add(buyer_instrument_balance)
        
        buyer_instrument_balance.amount += qty
        
        seller_instrument_balance = session.query(BalanceModel).with_for_update().filter(
            and_(
                BalanceModel.user_id == seller_id,
                BalanceModel.ticker == ticker
            )
        ).first()
        
        if not seller_instrument_balance:
            seller_instrument_balance = BalanceModel(
                user_id=seller_id,
                ticker=ticker,
                amount=0,
                locked_amount=0
            )
            session.add(seller_instrument_balance)
        
        seller_instrument_balance.amount -= qty

    def get_filled_quantity(self, session: Session, order_id: UUID) -> int:
        """Получение количества исполненных единиц заявки"""
        return session.query(func.sum(ExecutionModel.quantity)).filter(
            ExecutionModel.order_id == order_id
        ).scalar() or 0

    def get_order(self, order_id: UUID) -> Optional[Union[MarketOrder, LimitOrder]]:
        """Получение заявки по ID"""
        with self.get_session() as session:
            db_order = session.query(OrderModel).filter(OrderModel.id == order_id).first()
            if not db_order:
                return None

            if db_order.price is None:
                # Рыночная заявка
                return MarketOrder(
                    id=db_order.id,
                    status=db_order.status,
                    user_id=db_order.user_id,
                    timestamp=db_order.created_at,
                    body=MarketOrderBody(
                        direction=db_order.direction,
                        ticker=db_order.ticker,
                        qty=db_order.quantity
                    )
                )
            else:
                # Лимитная заявка
                return LimitOrder(
                    id=db_order.id,
                    status=db_order.status,
                    user_id=db_order.user_id,
                    timestamp=db_order.created_at,
                    body=LimitOrderBody(
                        direction=db_order.direction,
                        ticker=db_order.ticker,
                        qty=db_order.quantity,
                        price=db_order.price
                    ),
                    filled=self.get_filled_quantity(session, db_order.id)
                )

    def get_user_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        """Получение всех заявок пользователя"""
        try:
            logger.info(f"=== Starting get_user_orders ===")
            logger.info(f"User ID: {user_id}")
            
            with self.get_session() as session:
                logger.info("Querying orders from database")
                query = session.query(OrderModel).filter(OrderModel.user_id == str(user_id))
                query = query.order_by(OrderModel.created_at.desc())
                db_orders = query.all()
                logger.info(f"Found {len(db_orders)} raw orders in database")
                
                orders = []
                for order in db_orders:
                    try:
                        if order.price is None:
                            logger.info(f"Converting market order: id={order.id}")
                            market_order = MarketOrder(
                                id=order.id,
                                user_id=order.user_id,
                                timestamp=order.created_at,
                                body=MarketOrderBody(
                                    direction=order.direction,
                                    ticker=order.ticker,
                                    qty=order.quantity
                                ),
                                status=order.status
                            )
                            orders.append(market_order)
                        else:
                            logger.info(f"Converting limit order: id={order.id}, price={order.price}")
                            limit_order = LimitOrder(
                                id=order.id,
                                user_id=order.user_id,
                                timestamp=order.created_at,
                                body=LimitOrderBody(
                                    direction=order.direction,
                                    ticker=order.ticker,
                                    qty=order.quantity,
                                    price=order.price
                                ),
                                status=order.status
                            )
                            orders.append(limit_order)
                    except Exception as e:
                        logger.error(f"Error converting order {order.id}: {str(e)}", exc_info=True)
                        raise
                
                logger.info(f"Successfully converted {len(orders)} orders")
                logger.info(f"=== Completed get_user_orders ===")
                return orders
        except Exception as e:
            logger.error(f"Database error in get_user_orders: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get user orders: {str(e)}")

    def get_active_orders(self, user_id: UUID) -> List[Union[MarketOrder, LimitOrder]]:
        """Получение активных заявок пользователя"""
        with self.get_session() as session:
            db_orders = session.query(OrderModel).filter(
                and_(
                    OrderModel.user_id == user_id,
                    OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
                )
            ).all()
            return [
                MarketOrder(
                    id=order.id,
                    user_id=order.user_id,
                    timestamp=order.created_at,
                    body=MarketOrderBody(
                        direction=order.direction,
                        ticker=order.ticker,
                        qty=order.quantity
                    ),
                    status=order.status
                ) if order.price is None else
                LimitOrder(
                    id=order.id,
                    user_id=order.user_id,
                    timestamp=order.created_at,
                    body=LimitOrderBody(
                        direction=order.direction,
                        ticker=order.ticker,
                        qty=order.quantity,
                        price=order.price
                    ),
                    status=order.status
                )
                for order in db_orders
            ]

    def get_order_executions(self, order_id: UUID) -> List[ExecutionDetails]:
        """Получение истории исполнений заявки"""
        with self.get_session() as session:
            executions = session.query(ExecutionModel).filter(
                ExecutionModel.order_id == order_id
            ).all()
            
            return [
                ExecutionDetails(
                    execution_id=execution.id,
                    timestamp=execution.executed_at,
                    quantity=execution.quantity,
                    price=execution.price,
                    counterparty_order_id=execution.counterparty_order_id
                )
                for execution in executions
            ]

    def get_order_execution_summary(self, order_id: UUID) -> Optional[OrderExecutionSummary]:
        """Получение сводки по исполнению заявки"""
        with self.get_session() as session:
            executions = self.get_order_executions(order_id)
            if not executions:
                return None

            total_filled = sum(execution.quantity for execution in executions)
            total_value = sum(execution.quantity * execution.price for execution in executions)
            average_price = total_value / total_filled if total_filled > 0 else 0
            last_execution_time = max(execution.timestamp for execution in executions)

            return OrderExecutionSummary(
                total_filled=total_filled,
                average_price=average_price,
                last_execution_time=last_execution_time,
                executions=executions
            )

    def get_orderbook(self, ticker: str, limit: int = 10) -> L2OrderBook:
        """Получение стакана заявок по инструменту"""
        with self.get_session() as session:
            # Получаем все активные лимитные заявки для этого тикера
            active_orders = session.query(OrderModel).filter(
                and_(
                    OrderModel.ticker == ticker,
                    OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED]),
                    OrderModel.price.isnot(None)  # Только лимитные заявки
                )
            ).all()
        
            # Разделяем на покупки и продажи
            bids = [order for order in active_orders if order.direction == Direction.BUY]
            asks = [order for order in active_orders if order.direction == Direction.SELL]
        
            # Сортируем покупки по убыванию цены (лучшие цены сверху)
            bids.sort(key=lambda x: x.price, reverse=True)
            # Сортируем продажи по возрастанию цены (лучшие цены сверху)
            asks.sort(key=lambda x: x.price)
        
            # Группируем заявки по ценам
            bid_levels = {}
            for order in bids:
                remaining_qty = order.quantity - self.get_filled_quantity(session, order.id)
                if remaining_qty <= 0:
                    continue
                if order.price not in bid_levels:
                    bid_levels[order.price] = 0
                bid_levels[order.price] += remaining_qty
        
            ask_levels = {}
            for order in asks:
                remaining_qty = order.quantity - self.get_filled_quantity(session, order.id)
                if remaining_qty <= 0:
                    continue
                if order.price not in ask_levels:
                    ask_levels[order.price] = 0
                ask_levels[order.price] += remaining_qty
        
            # Преобразуем в список уровней
            bid_levels_list = [Level(price=price, qty=qty) for price, qty in bid_levels.items()]
            ask_levels_list = [Level(price=price, qty=qty) for price, qty in ask_levels.items()]
        
            # Ограничиваем количество уровней
            return L2OrderBook(
                bid_levels=bid_levels_list[:limit],
                ask_levels=ask_levels_list[:limit]
            )

    def deposit_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        """Пополнение баланса пользователя"""
        self.update_balance(user_id, ticker, amount)

    def withdraw_balance(self, user_id: UUID, ticker: str, amount: int) -> None:
        """Списание средств с баланса пользователя"""
        self.update_balance(user_id, ticker, -amount)

    def get_active_orders_by_ticker(self, ticker: str) -> list:
        """Получение всех активных заявок по тикеру"""
        with self.get_session() as session:
            return session.query(OrderModel).filter(
                OrderModel.ticker == ticker,
                OrderModel.status.in_([OrderStatus.NEW, OrderStatus.PARTIALLY_EXECUTED])
            ).all()

    def get_all_instruments(self) -> List[Instrument]:
        """Получение списка всех активных инструментов"""
        try:
            with self.get_session() as session:
                db_instruments = session.query(InstrumentModel).filter(
                    InstrumentModel.is_active == True
                ).all()
                
                return [
                    Instrument(
                        ticker=db_instrument.ticker,
                        name=db_instrument.name
                    )
                    for db_instrument in db_instruments
                ]
        except DatabaseError as e:
            raise DatabaseError(f"Failed to get instruments: {str(e)}")

    def get_best_price(self, ticker: str, direction: Direction) -> Optional[int]:
        """Получение лучшей цены для рыночной заявки
        
        Args:
            ticker: Тикер инструмента
            direction: Направление заявки (BUY/SELL)
            
        Returns:
            Optional[int]: Лучшая доступная цена или None, если нет подходящих заявок
        """
        try:
            logger.info(f"Getting best price for {ticker} {direction}")
            with self.get_session() as session:
                # Для покупки ищем минимальную цену продажи
                if direction == Direction.BUY:
                    order = session.query(OrderModel)\
                        .filter(
                            OrderModel.ticker == ticker,
                            OrderModel.direction == Direction.SELL,
                            OrderModel.status == OrderStatus.ACTIVE,
                            OrderModel.type == OrderType.LIMIT
                        )\
                        .order_by(OrderModel.price.asc())\
                        .first()
                # Для продажи ищем максимальную цену покупки
                else:
                    order = session.query(OrderModel)\
                        .filter(
                            OrderModel.ticker == ticker,
                            OrderModel.direction == Direction.BUY,
                            OrderModel.status == OrderStatus.ACTIVE,
                            OrderModel.type == OrderType.LIMIT
                        )\
                        .order_by(OrderModel.price.desc())\
                        .first()
                
                if order:
                    logger.info(f"Found best price: {order.price}")
                    return order.price
                logger.warning(f"No active orders found for {ticker} {direction}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting best price: {str(e)}", exc_info=True)
            raise DatabaseError(f"Failed to get best price: {str(e)}")

# Create a global database instance
db = Database("postgresql://postgres:postgres@db:5432/stock_exchange") 