"""add users temporary_password_expires_at

Revision ID: 74ff2b7630c0
Revises: f44f6b069ec6
Create Date: 2026-11-25 12:00:00.000000

users.temporary_password_expires_at: set while the user's password is
temporary (chosen by someone else), and must be changed. NULL, the value for
every existing user, means a normal password.

Rollback restrictions:
    - Images built before this migration ignore the column: a temporary
      password works like a normal one, without a forced change or expiry.
    - A password changed or reset by such an image leaves the column as it
      was. After rolling forward, a user still marked temporary must change
      the password again, or needs a reset if it has expired.
    - Downgrading forgets which passwords are temporary; they become normal.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74ff2b7630c0'
down_revision: Union[str, Sequence[str], None] = 'f44f6b069ec6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('temporary_password_expires_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'temporary_password_expires_at')
