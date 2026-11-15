"""drop task business trigger

Revision ID: 2bd7ae5baabe
Revises: abfef75f2975
Create Date: 2026-11-14 20:45:33.856238

Removes the temporary measure from b840ad91c0f4: the trigger
tasks_fill_business_id and its function. Every application version since
that migration sets tasks.business_id itself.

Rollback restrictions:
    - Images built before b840ad91c0f4 can no longer create tasks: their
      inserts omit the required business_id. Downgrading this migration
      restores the trigger and makes them work again.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2bd7ae5baabe'
down_revision: Union[str, Sequence[str], None] = 'abfef75f2975'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DROP TRIGGER tasks_fill_business_id ON tasks")
    op.execute("DROP FUNCTION tasks_fill_business_id()")


def downgrade() -> None:
    """Downgrade schema."""
    # Same definition as in b840ad91c0f4.
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
