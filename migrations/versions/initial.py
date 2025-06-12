"""initial

Revision ID: initial
Create Date: 2024-02-09 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from app.schemas.user import UserRole
from app.schemas.order import OrderStatus, Direction


# revision identifiers, used by Alembic.
revision = 'initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Применение миграции:
    1. Создание таблиц с правильными связями
    """
    # Создаем таблицы внутри транзакции
    with op.get_context().begin_transaction():
        # Создаем таблицу пользователей
        op.create_table(
            'users',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('role', sa.Enum(UserRole, name='user_role'), nullable=False),
            sa.Column('api_key', sa.String(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('api_key'),
            sa.CheckConstraint("length(name) >= 3", name="user_name_length_check")
        )
        
        # Создаем таблицу инструментов
        op.create_table(
            'instruments',
            sa.Column('ticker', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.PrimaryKeyConstraint('ticker'),
            sa.CheckConstraint("ticker ~ '^[A-Z]{2,10}$'", name="ticker_format_check")
        )
        
        # Создаем таблицу балансов
        op.create_table(
            'balances',
            sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('ticker', sa.String(), nullable=False),
            sa.Column('amount', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ['user_id'], ['users.id'],
                ondelete='CASCADE',
                name='balance_user_fk'
            ),
            sa.ForeignKeyConstraint(
                ['ticker'], ['instruments.ticker'],
                ondelete='CASCADE',
                name='balance_instrument_fk'
            ),
            sa.PrimaryKeyConstraint('user_id', 'ticker'),
            sa.CheckConstraint('amount >= 0', name='balance_amount_check')
        )
        
        # Создаем таблицу ордеров
        op.create_table(
            'orders',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('ticker', sa.String(), nullable=False),
            sa.Column('direction', sa.Enum(Direction, name='direction'), nullable=False),
            sa.Column('status', sa.Enum(OrderStatus, name='order_status'), nullable=False),
            sa.Column('qty', sa.Integer(), nullable=False),
            sa.Column('price', sa.Integer(), nullable=True),
            sa.Column('filled', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(
                ['user_id'], ['users.id'],
                ondelete='CASCADE',
                name='order_user_fk'
            ),
            sa.ForeignKeyConstraint(
                ['ticker'], ['instruments.ticker'],
                ondelete='CASCADE',
                name='order_instrument_fk'
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint('qty > 0', name='order_qty_check'),
            sa.CheckConstraint('price > 0 OR price IS NULL', name='order_price_check'),
            sa.CheckConstraint('filled >= 0 AND filled <= qty', name='order_filled_check')
        )
        
        # Создаем таблицу транзакций
        op.create_table(
            'transactions',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('ticker', sa.String(), nullable=False),
            sa.Column('buyer_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('seller_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('amount', sa.Integer(), nullable=False),
            sa.Column('price', sa.Integer(), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(
                ['buyer_id'], ['users.id'],
                ondelete='CASCADE',
                name='transaction_buyer_fk'
            ),
            sa.ForeignKeyConstraint(
                ['seller_id'], ['users.id'],
                ondelete='CASCADE',
                name='transaction_seller_fk'
            ),
            sa.ForeignKeyConstraint(
                ['ticker'], ['instruments.ticker'],
                ondelete='CASCADE',
                name='transaction_instrument_fk'
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint('amount > 0', name='transaction_amount_check'),
            sa.CheckConstraint('price > 0', name='transaction_price_check'),
            sa.CheckConstraint('buyer_id != seller_id', name='transaction_different_users_check')
        )
        
        # Создаем индексы для оптимизации запросов
        op.create_index('ix_orders_user_id', 'orders', ['user_id'])
        op.create_index('ix_orders_ticker', 'orders', ['ticker'])
        op.create_index('ix_orders_timestamp', 'orders', ['timestamp'])
        op.create_index('ix_transactions_ticker', 'transactions', ['ticker'])
        op.create_index('ix_transactions_timestamp', 'transactions', ['timestamp'])
        op.create_index('ix_balances_user_id', 'balances', ['user_id'])


def downgrade() -> None:
    """
    Откат миграции:
    1. Удаление таблиц в правильном порядке
    """
    # Удаляем таблицы внутри транзакции
    with op.get_context().begin_transaction():
        # Сначала удаляем индексы
        op.drop_index('ix_transactions_timestamp')
        op.drop_index('ix_transactions_ticker')
        op.drop_index('ix_orders_timestamp')
        op.drop_index('ix_orders_ticker')
        op.drop_index('ix_orders_user_id')
        op.drop_index('ix_balances_user_id')
        
        # Затем удаляем таблицы в порядке зависимостей
        op.drop_table('transactions')
        op.drop_table('orders')
        op.drop_table('balances')
        op.drop_table('instruments')
        op.drop_table('users')