"""add users tokens_valid_after

Revision ID: f44f6b069ec6
Revises: 0496b5c9c61f
Create Date: 2026-11-22 12:00:00.000000

users.tokens_valid_after: login tokens issued before this moment are refused.
Changing or resetting a password, or ending a user's sessions, sets it.
NULL, the value for every existing user, means no cut-off.

Rollback restrictions:
    - Images built before this migration ignore the column: after a password
      change or reset, older tokens stay valid until they expire (30 minutes).
    - Downgrading forgets every cut-off; the same 30-minute limit applies.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f44f6b069ec6'
down_revision: Union[str, Sequence[str], None] = '0496b5c9c61f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('tokens_valid_after', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'tokens_valid_after')
