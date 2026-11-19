"""Subdomains: login fields optional, display name/notes/retired_at, subdomain_status table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUBDOMAIN_STATE = postgresql.ENUM(
    'ready', 'dns_missing', 'no_inbox', 'suspended', 'retired', 'unknown',
    name='subdomain_state', create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('users', 'email', existing_type=sa.Text(), nullable=True)
    op.alter_column('users', 'email_hash', existing_type=sa.String(length=64), nullable=True)
    op.alter_column('users', 'password_hash', existing_type=sa.String(), nullable=True)
    op.add_column('users', sa.Column('display_name', sa.String(length=80), nullable=True))
    op.add_column('users', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True))

    SUBDOMAIN_STATE.create(op.get_bind(), checkfirst=True)
    op.create_table('subdomain_status',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('state', SUBDOMAIN_STATE, nullable=False),
    sa.Column('mx_ok', sa.Boolean(), nullable=True),
    sa.Column('spf_ok', sa.Boolean(), nullable=True),
    sa.Column('kv_ok', sa.Boolean(), nullable=True),
    sa.Column('detail', sa.String(length=200), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_subdomain_status_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_subdomain_status'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    missing = op.get_bind().execute(
        sa.text('SELECT count(*) FROM users WHERE email IS NULL OR email_hash IS NULL OR password_hash IS NULL')
    ).scalar()
    if missing:
        raise RuntimeError(
            f'{missing} subdomain(s) have no email or password; the old schema requires both. '
            'Retire or give them credentials before downgrading.'
        )
    op.drop_table('subdomain_status')
    SUBDOMAIN_STATE.drop(op.get_bind(), checkfirst=True)
    op.drop_column('users', 'retired_at')
    op.drop_column('users', 'notes')
    op.drop_column('users', 'display_name')
    op.alter_column('users', 'password_hash', existing_type=sa.String(), nullable=False)
    op.alter_column('users', 'email_hash', existing_type=sa.String(length=64), nullable=False)
    op.alter_column('users', 'email', existing_type=sa.Text(), nullable=False)
