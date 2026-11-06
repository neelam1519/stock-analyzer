from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('backtest_runs', sa.Column('kind', sa.String(length=16), nullable=True), schema='res')
    op.add_column('backtest_runs', sa.Column('metrics_json', sa.UnicodeText(), nullable=True), schema='res')
    op.add_column('backtest_runs', sa.Column('equity_json', sa.UnicodeText(), nullable=True), schema='res')


def downgrade() -> None:
    op.drop_column('backtest_runs', 'equity_json', schema='res')
    op.drop_column('backtest_runs', 'metrics_json', schema='res')
    op.drop_column('backtest_runs', 'kind', schema='res')
