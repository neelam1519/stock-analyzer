from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_runs', sa.Column('details', sa.Unicode(length=1000), nullable=True), schema='app')


def downgrade() -> None:
    op.drop_column('job_runs', 'details', schema='app')
