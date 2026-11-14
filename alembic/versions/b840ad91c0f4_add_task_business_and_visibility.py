"""add task business and visibility

Revision ID: b840ad91c0f4
Revises: 586fecaea66f
Create Date: 2026-11-14 12:00:00.000000

Gives each task the business of its owner, enforced by a foreign key on
(business_id, owner_id) so a task can never belong to another business than
its owner. Adds users.sees_all_tasks: whether a user sees every task in
their business. Existing admins get true, so they keep seeing all tasks
once the application uses the setting; members keep seeing their own.

Temporary compatibility measure:
    The trigger tasks_fill_business_id copies business_id from the owner
    when an insert omits it, so the application version running during
    this migration, and images built before it, can still create tasks.
    Remove it in a later migration once no such image can be deployed or
    restored.

Rollback restrictions:
    - Images built before this migration stay compatible while the trigger
      exists; they ignore sees_all_tasks and show users only their own tasks.
    - Downgrading removes tasks.business_id and every user's
      sees_all_tasks setting.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b840ad91c0f4'
down_revision: Union[str, Sequence[str], None] = '586fecaea66f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('sees_all_tasks', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE users SET sees_all_tasks = true WHERE role = 'admin'")

    # Redundant with the primary key, but PostgreSQL requires a unique
    # target for the composite foreign key below.
    op.create_unique_constraint('uq_users_business_id_id', 'users', ['business_id', 'id'])

    # Added empty, filled from each owner, then made required.
    op.add_column('tasks', sa.Column('business_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE tasks SET business_id = users.business_id "
        "FROM users WHERE users.id = tasks.owner_id"
    )
    op.alter_column('tasks', 'business_id', nullable=False)
    op.create_index('ix_tasks_business_id', 'tasks', ['business_id'])
    op.create_foreign_key(
        'fk_tasks_business_id_owner_id_users',
        'tasks',
        'users',
        ['business_id', 'owner_id'],
        ['business_id', 'id'],
    )

    op.execute(
        """
        CREATE FUNCTION tasks_fill_business_id() RETURNS trigger AS $$
        BEGIN
            IF NEW.business_id IS NULL THEN
                SELECT business_id INTO NEW.business_id
                FROM users WHERE id = NEW.owner_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER tasks_fill_business_id BEFORE INSERT ON tasks "
        "FOR EACH ROW EXECUTE FUNCTION tasks_fill_business_id()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER tasks_fill_business_id ON tasks")
    op.execute("DROP FUNCTION tasks_fill_business_id()")
    op.drop_constraint('fk_tasks_business_id_owner_id_users', 'tasks', type_='foreignkey')
    op.drop_index('ix_tasks_business_id', table_name='tasks')
    op.drop_column('tasks', 'business_id')
    op.drop_constraint('uq_users_business_id_id', 'users', type_='unique')
    op.drop_column('users', 'sees_all_tasks')
