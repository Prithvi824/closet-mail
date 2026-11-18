"""Default inboxes: recipients.forward_by_default, backfilled from users.default_recipient_id.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-18 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'recipients',
        sa.Column('forward_by_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    # users.default_recipient_id stays until the cleanup migration: old containers still read it.
    op.execute(
        'UPDATE recipients r SET forward_by_default = true '
        'FROM users u WHERE u.default_recipient_id = r.id'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recipients', 'forward_by_default')
