"""add app database role

Revision ID: 670248a338cd
Revises: 46c6a6bfb8b4
Create Date: 2026-11-08 12:00:00.000000

Creates the task_manager_app role and grants it only the data access the
running application needs: reading and writing rows, and using the sequences
that number new rows. It cannot create, alter, or drop tables, manage roles,
or change the Alembic revision. Migrations keep running as the owner of the
schema (the RDS master user in production).

The role is created without a password, so it cannot log in yet. The
operator sets its password in production; CI sets a test-only one.

Default privileges give tables and sequences created later by the migration
user the same grants, so future migrations need no extra grant step. They
apply only to objects created by the user that ran this migration.

Compatibility:
    No table or row changes. The running application keeps its current
    database user until it is switched to task_manager_app.

Rollback restrictions:
    - Downgrading removes the grants but keeps the role, because roles are
      shared by every database on the server.
    - Once the application connects as task_manager_app, downgrading below
      this revision removes its access and stops the application. Switch it
      back to the migration user first.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '670248a338cd'
down_revision: Union[str, Sequence[str], None] = '46c6a6bfb8b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APP_ROLE = "task_manager_app"


def upgrade() -> None:
    """Upgrade schema."""
    # Roles exist once per server; another database may have created it.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    # The application only reads the revision (alembic current); migrations write it.
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE}")

    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
