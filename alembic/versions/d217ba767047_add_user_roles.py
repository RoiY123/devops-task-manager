"""add user roles

Revision ID: d217ba767047
Revises: 652cc0a22e68
Create Date: 2026-10-23 12:00:00.000000

Every user gets a role: "admin" or "member". Existing users become members.

Compatibility:
    users.role has a permanent database default of "member". Application
    versions before this migration do not set a role, so their new users
    become members. This default is intentionally kept: a missing role can
    only ever grant the lowest permission.

Rollback restrictions:
    - Images built before this migration remain compatible with the schema.
    - Downgrading removes the role column. It is lossless only while no user
      is an admin; once businesses have been onboarded with administrators,
      a downgrade forgets who the administrators are.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd217ba767047'
down_revision: Union[str, Sequence[str], None] = '652cc0a22e68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A constant default fills existing rows without rewriting the table.
    op.add_column(
        'users',
        sa.Column(
            'role',
            sa.String(length=20),
            server_default='member',
            nullable=False,
        ),
    )
    op.create_check_constraint(
        'ck_users_role',
        'users',
        "role IN ('admin', 'member')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_users_role', 'users', type_='check')
    op.drop_column('users', 'role')
