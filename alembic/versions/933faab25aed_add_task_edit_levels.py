"""add task edit levels

Revision ID: 933faab25aed
Revises: f4c26d7e2c28
Create Date: 2026-11-16 17:48:23.641022

Admins always see every task in their business (ck_users_admin_sees_all);
existing admins are switched to see all. users.edits_all_tasks lets a user
change every task, and requires seeing all (ck_users_edits_all_needs_sees_all).
Grants may now be 'edit': see and change the owner's tasks. Grants whose
viewer sees all tasks had no effect and are deleted.

Rollback restrictions:
    - Images built before this migration let every admin change every task
      they can see, ignore edits_all_tasks, and treat edit grants as view
      grants. Their set-task-visibility cannot limit an admin: the database
      refuses it.
    - Downgrading turns edit grants into view grants and forgets
      edits_all_tasks; admins keep seeing all tasks.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '933faab25aed'
down_revision: Union[str, Sequence[str], None] = 'f4c26d7e2c28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE users SET sees_all_tasks = true WHERE role = 'admin'")
    op.execute(
        "DELETE FROM task_grants USING users "
        "WHERE users.id = task_grants.viewer_id AND users.sees_all_tasks"
    )
    op.add_column(
        'users',
        sa.Column(
            'edits_all_tasks', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_check_constraint(
        'ck_users_admin_sees_all', 'users', "role <> 'admin' OR sees_all_tasks"
    )
    op.create_check_constraint(
        'ck_users_edits_all_needs_sees_all',
        'users',
        "NOT edits_all_tasks OR sees_all_tasks",
    )
    op.drop_constraint('ck_task_grants_permission', 'task_grants', type_='check')
    op.create_check_constraint(
        'ck_task_grants_permission', 'task_grants', "permission IN ('view', 'edit')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE task_grants SET permission = 'view' WHERE permission = 'edit'")
    op.drop_constraint('ck_task_grants_permission', 'task_grants', type_='check')
    op.create_check_constraint(
        'ck_task_grants_permission', 'task_grants', "permission IN ('view')"
    )
    op.drop_constraint('ck_users_edits_all_needs_sees_all', 'users', type_='check')
    op.drop_constraint('ck_users_admin_sees_all', 'users', type_='check')
    op.drop_column('users', 'edits_all_tasks')
