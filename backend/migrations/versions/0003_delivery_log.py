"""Delivery logging: delivery_log table, received time and sender domain on mail_log, outcome counters.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DELIVERY_STATUS = postgresql.ENUM(
    'sent', 'delivered', 'bounced', 'complained', 'delayed', name='delivery_status', create_type=False
)
USAGE_COUNTERS = ('received', 'quarantined', 'blocked', 'discarded')


def upgrade() -> None:
    """Upgrade schema."""
    DELIVERY_STATUS.create(op.get_bind(), checkfirst=True)
    op.create_table('delivery_log',
    sa.Column('mail_log_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('recipient_id', sa.Uuid(), nullable=True),
    sa.Column('provider_id', sa.String(length=128), nullable=True),
    sa.Column('status', DELIVERY_STATUS, nullable=False),
    sa.Column('status_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['mail_log_id'], ['mail_log.id'], name=op.f('fk_delivery_log_mail_log_id_mail_log'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_delivery_log_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_id'], ['recipients.id'], name=op.f('fk_delivery_log_recipient_id_recipients'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_log')),
    sa.UniqueConstraint('provider_id', name=op.f('uq_delivery_log_provider_id'))
    )
    op.create_index(op.f('ix_delivery_log_mail_log_id'), 'delivery_log', ['mail_log_id'], unique=False)
    op.create_index(op.f('ix_delivery_log_user_id'), 'delivery_log', ['user_id'], unique=False)

    op.add_column('mail_log', sa.Column('received_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mail_log', sa.Column('sender_domain_hash', sa.String(length=64), nullable=True))
    op.add_column('mail_log', sa.Column('sender_domain', sa.Text(), nullable=True))
    op.create_index('ix_mail_log_created_at', 'mail_log', ['created_at'], unique=False)
    op.create_index('ix_mail_log_user_received', 'mail_log', ['user_id', 'received_at'], unique=False)
    op.create_index(op.f('ix_mail_log_sender_domain_hash'), 'mail_log', ['sender_domain_hash'], unique=False)

    for column in USAGE_COUNTERS:
        op.add_column('usage_daily', sa.Column(column, sa.Integer(), server_default='0', nullable=False))

    # Old rows have no edge timestamp; their processing time is the closest we have.
    op.execute('UPDATE mail_log SET received_at = created_at WHERE received_at IS NULL')


def downgrade() -> None:
    """Downgrade schema."""
    for column in USAGE_COUNTERS:
        op.drop_column('usage_daily', column)
    op.drop_index(op.f('ix_mail_log_sender_domain_hash'), table_name='mail_log')
    op.drop_index('ix_mail_log_user_received', table_name='mail_log')
    op.drop_index('ix_mail_log_created_at', table_name='mail_log')
    op.drop_column('mail_log', 'sender_domain')
    op.drop_column('mail_log', 'sender_domain_hash')
    op.drop_column('mail_log', 'received_at')
    op.drop_index(op.f('ix_delivery_log_user_id'), table_name='delivery_log')
    op.drop_index(op.f('ix_delivery_log_mail_log_id'), table_name='delivery_log')
    op.drop_table('delivery_log')
    DELIVERY_STATUS.drop(op.get_bind(), checkfirst=True)
