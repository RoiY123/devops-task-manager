"""add task grants

Revision ID: abfef75f2975
Revises: b840ad91c0f4
Create Date: 2026-11-14 20:35:27.730098

Adds task_grants: a row lets the viewer see every task of the owner in the
same business. Only the 'view' permission exists; allowing 'edit' later
extends ck_task_grants_permission.

Rollback restrictions:
    - Images built before this migration ignore grants: viewers see only
      what sees_all_tasks allows.
    - Downgrading deletes every grant.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abfef75f2975'
down_revision: Union[str, Sequence[str], None] = 'b840ad91c0f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'task_grants',
        sa.Column('viewer_id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('business_id', sa.Integer(), nullable=False),
        sa.Column('permission', sa.String(20), nullable=False, server_default='view'),
        sa.PrimaryKeyConstraint('viewer_id', 'owner_id', name='pk_task_grants'),
        sa.ForeignKeyConstraint(
            ['business_id', 'viewer_id'],
            ['users.business_id', 'users.id'],
            name='fk_task_grants_business_id_viewer_id_users',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['business_id', 'owner_id'],
            ['users.business_id', 'users.id'],
            name='fk_task_grants_business_id_owner_id_users',
            ondelete='CASCADE',
        ),
        sa.CheckConstraint('viewer_id <> owner_id', name='ck_task_grants_not_self'),
        sa.CheckConstraint("permission IN ('view')", name='ck_task_grants_permission'),
    )
    op.create_index('ix_task_grants_owner_id', 'task_grants', ['owner_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_task_grants_owner_id', table_name='task_grants')
    op.drop_table('task_grants')
