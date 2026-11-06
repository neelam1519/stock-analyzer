from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('approval_queue', sa.Column('kind', sa.String(length=8), nullable=True), schema='trd')
    op.add_column('approval_queue', sa.Column('position_id', sa.BigInteger(), nullable=True), schema='trd')
    op.add_column('approval_queue', sa.Column('reason', sa.Unicode(length=300), nullable=True), schema='trd')
    op.add_column('live_orders', sa.Column('kind', sa.String(length=16), nullable=True), schema='trd')
    op.add_column('live_orders', sa.Column('position_id', sa.BigInteger(), nullable=True), schema='trd')
    op.add_column('live_orders', sa.Column('status_message', sa.Unicode(length=500), nullable=True), schema='trd')
    op.add_column('live_orders', sa.Column('filled_qty', sa.Integer(), nullable=True), schema='trd')
    op.add_column('live_orders', sa.Column('average_price', sa.Numeric(precision=18, scale=4), nullable=True), schema='trd')
    op.alter_column('live_orders', 'approval_id',
               existing_type=sa.BIGINT(),
               nullable=True,
               schema='trd')


def downgrade() -> None:
    op.alter_column('live_orders', 'approval_id',
               existing_type=sa.BIGINT(),
               nullable=False,
               schema='trd')
    op.drop_column('live_orders', 'average_price', schema='trd')
    op.drop_column('live_orders', 'filled_qty', schema='trd')
    op.drop_column('live_orders', 'status_message', schema='trd')
    op.drop_column('live_orders', 'position_id', schema='trd')
    op.drop_column('live_orders', 'kind', schema='trd')
    op.drop_column('approval_queue', 'reason', schema='trd')
    op.drop_column('approval_queue', 'position_id', schema='trd')
    op.drop_column('approval_queue', 'kind', schema='trd')
