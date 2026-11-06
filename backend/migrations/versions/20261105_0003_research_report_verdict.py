from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('research_reports', sa.Column('key_risks', sa.UnicodeText(), nullable=True), schema='res')
    op.add_column('research_reports', sa.Column('verdict', sa.String(length=8), nullable=True), schema='res')
    op.add_column('research_reports', sa.Column('prompt_version', sa.String(length=16), nullable=True), schema='res')


def downgrade() -> None:
    op.drop_column('research_reports', 'prompt_version', schema='res')
    op.drop_column('research_reports', 'verdict', schema='res')
    op.drop_column('research_reports', 'key_risks', schema='res')
