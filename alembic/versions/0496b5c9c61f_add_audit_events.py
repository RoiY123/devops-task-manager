"""add audit events

Revision ID: 0496b5c9c61f
Revises: 933faab25aed
Create Date: 2026-11-21 13:16:44.409262

Adds audit_events: one row per successful change to users, task access or
businesses, written in the same transaction as the change. Rows copy the
business slug and the users' emails and have no foreign keys, so the history
outlives removed users and deleted businesses.

The application role may insert and read rows but not update or delete them,
so even a compromised application cannot rewrite or erase history; only the
schema owner can.

Rollback restrictions:
    - Images built before this migration write no events: changes made during
      the deploy overlap, or while rolled back, are not recorded.
    - Downgrading drops the table and every recorded event.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0496b5c9c61f'
down_revision: Union[str, Sequence[str], None] = '933faab25aed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "task_manager_app"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'audit_events',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column(
            'occurred_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column('business_id', sa.Integer(), nullable=False),
        sa.Column('business_slug', sa.String(63), nullable=False),
        sa.Column('actor_kind', sa.String(10), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_email', sa.String(320), nullable=True),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=True),
        sa.Column('target_email', sa.String(320), nullable=True),
        sa.Column(
            'details',
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint('id', name='pk_audit_events'),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'operator')", name='ck_audit_events_actor_kind'
        ),
        # A user event names its user; an operator event names no one.
        # Unknown kinds are left to ck_audit_events_actor_kind,
        # so each refusal names the rule that was broken.
        sa.CheckConstraint(
            "(actor_kind <> 'user' OR (actor_user_id IS NOT NULL AND actor_email IS NOT NULL))"
            " AND (actor_kind <> 'operator' OR (actor_user_id IS NULL AND actor_email IS NULL))",
            name='ck_audit_events_actor',
        ),
    )
    op.create_index(
        'ix_audit_events_business_id_occurred_at',
        'audit_events',
        ['business_id', 'occurred_at'],
    )
    # Default privileges gave the app full access to the new table;
    # take back the two that could change history.
    op.execute(f"REVOKE UPDATE, DELETE ON audit_events FROM {APP_ROLE}")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_audit_events_business_id_occurred_at', table_name='audit_events')
    op.drop_table('audit_events')
