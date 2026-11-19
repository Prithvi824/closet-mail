"""Cleanup: drop users.default_recipient_id (replaced by recipients.forward_by_default) and invites.

Deploy only after 0004 has been running in production: containers older than 0004 still read
users.default_recipient_id.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Created in 0001 with use_alter (users and recipients reference each other).
    op.drop_constraint('fk_users_default_recipient_id_recipients', 'users', type_='foreignkey')
    op.drop_column('users', 'default_recipient_id')
    op.drop_index(op.f('ix_invites_email_hash'), table_name='invites')
    op.drop_table('invites')


def downgrade() -> None:
    """Downgrade schema (both come back empty; flags in recipients.forward_by_default stay)."""
    op.create_table('invites',
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('email_hash', sa.String(length=64), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('invited_by', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_invites_invited_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invites')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_invites_token_hash'))
    )
    op.create_index(op.f('ix_invites_email_hash'), 'invites', ['email_hash'], unique=False)
    op.add_column('users', sa.Column('default_recipient_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_users_default_recipient_id_recipients',
        'users',
        'recipients',
        ['default_recipient_id'],
        ['id'],
        ondelete='SET NULL',
    )
