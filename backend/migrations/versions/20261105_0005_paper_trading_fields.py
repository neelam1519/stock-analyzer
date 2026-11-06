from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('paper_orders', sa.Column('as_of_date', sa.Date(), nullable=True), schema='trd')
    op.add_column('paper_orders', sa.Column('stop_loss', sa.Numeric(precision=18, scale=4), nullable=True), schema='trd')
    op.add_column('paper_orders', sa.Column('target', sa.Numeric(precision=18, scale=4), nullable=True), schema='trd')
    op.add_column('paper_orders', sa.Column('position_id', sa.BigInteger(), nullable=True), schema='trd')
    op.add_column('paper_orders', sa.Column('reason', sa.String(length=200), nullable=True), schema='trd')
    op.add_column('positions', sa.Column('initial_stop', sa.Numeric(precision=18, scale=4), nullable=True), schema='trd')
    op.add_column('positions', sa.Column('highest_close', sa.Numeric(precision=18, scale=4), nullable=True), schema='trd')
    op.add_column('positions', sa.Column('last_price', sa.Numeric(precision=18, scale=4), nullable=True), schema='trd')
    op.add_column('positions', sa.Column('last_price_at', sa.DateTime(), nullable=True), schema='trd')
    op.add_column('positions', sa.Column('exit_reason', sa.String(length=32), nullable=True), schema='trd')


def downgrade() -> None:
    op.drop_column('positions', 'exit_reason', schema='trd')
    op.drop_column('positions', 'last_price_at', schema='trd')
    op.drop_column('positions', 'last_price', schema='trd')
    op.drop_column('positions', 'highest_close', schema='trd')
    op.drop_column('positions', 'initial_stop', schema='trd')
    op.drop_column('paper_orders', 'reason', schema='trd')
    op.drop_column('paper_orders', 'position_id', schema='trd')
    op.drop_column('paper_orders', 'target', schema='trd')
    op.drop_column('paper_orders', 'stop_loss', schema='trd')
    op.drop_column('paper_orders', 'as_of_date', schema='trd')
