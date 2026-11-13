"""email unique per business

Revision ID: 586fecaea66f
Revises: 670248a338cd
Create Date: 2026-11-13 12:00:00.000000

Replaces the global unique email index with one unique per business that
ignores capitals: the same email may belong to different businesses, while
one business cannot hold Dana@x and dana@x.

Compatibility:
    The application version running during this migration logs users in
    within their business, so it keeps working. Creating the index briefly
    blocks writes to users.

Rollback restrictions:
    - Images built from the business-specific login release onwards are
      compatible.
    - Images built before it are unsafe once an email exists in two
      businesses: their POST /login could sign in to the wrong account.
    - Downgrading is refused while any email exists in more than one
      business, because the global index could not be restored.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '586fecaea66f'
down_revision: Union[str, Sequence[str], None] = '670248a338cd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Created first: it fails, and nothing changes,
    # if a business holds emails that differ only in capitals.
    op.create_index(
        'uq_users_business_id_lower_email',
        'users',
        ['business_id', sa.text('lower(email)')],
        unique=True,
    )
    op.drop_index('ix_users_email', table_name='users')


def downgrade() -> None:
    """Downgrade schema."""
    shared = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM ("
            "SELECT email FROM users GROUP BY email HAVING count(*) > 1"
            ") AS shared_emails"
        )
    ).scalar_one()

    if shared:
        # Only the count: deployment logs should not contain email addresses.
        raise RuntimeError(
            f"Cannot restore globally unique emails: {shared} email(s) exist "
            "in more than one business"
        )

    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.drop_index('uq_users_business_id_lower_email', table_name='users')
