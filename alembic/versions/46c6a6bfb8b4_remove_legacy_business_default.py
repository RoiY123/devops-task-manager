"""remove legacy business default

Revision ID: 46c6a6bfb8b4
Revises: d217ba767047
Create Date: 2026-10-24 12:00:00.000000

Removes the temporary users.business_id default added in 652cc0a22e68.
Public registration is closed in the same release, so every code path that
creates users sets business_id explicitly. A user without a business is now
rejected instead of silently joining the legacy business.

Compatibility:
    The application version running during this migration sets business_id
    explicitly, so it keeps working while the migration runs.

Rollback restrictions:
    - Images built from 652cc0a22e68 onwards remain compatible. Images built
      before this migration still contain /register, so rolling back to one
      reopens public registration until the next deploy.
    - Rolling back to an image built before 652cc0a22e68 is not supported:
      it inserts users without business_id, which now fails.
    - Downgrading restores the default and requires the legacy business.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46c6a6bfb8b4'
down_revision: Union[str, Sequence[str], None] = 'd217ba767047'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_SLUG = "legacy"


def upgrade() -> None:
    """Upgrade schema."""
    # Only the column's default changes; no rows are read or rewritten.
    op.alter_column('users', 'business_id', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    legacy_id = op.get_bind().execute(
        sa.text("SELECT id FROM businesses WHERE slug = :slug"),
        {"slug": LEGACY_SLUG},
    ).scalar_one_or_none()

    if legacy_id is None:
        raise RuntimeError(
            "Cannot restore the business_id default: "
            "the legacy business is missing"
        )

    # PostgreSQL defaults cannot contain subqueries, so the id is a literal.
    op.alter_column(
        'users',
        'business_id',
        server_default=sa.text(str(int(legacy_id))),
    )
