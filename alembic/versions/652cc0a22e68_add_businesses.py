"""add businesses

Revision ID: 652cc0a22e68
Revises: 32721ce95d01
Create Date: 2026-10-06 12:00:00.000000

Hand-written: this migration moves data.

Every existing user is assigned to a business with slug "legacy".

Temporary compatibility measure:
    users.business_id has a database default pointing at the legacy
    business. Application versions before this migration do not set
    business_id, so the default lets them register users while the
    migration runs, after a failed deployment, or after an
    application-only rollback. Current application code sets business_id
    explicitly and must not rely on the default.

Removal condition:
    Remove the default when public registration is closed, once every
    deployable or rollback-candidate image sets business_id explicitly.
    Keeping it longer risks silently placing users in the legacy business.

Rollback restrictions:
    - While the default exists, images built before this migration remain
      compatible with the schema.
    - After the default is removed, rolling back to an image built before
      this migration is not supported.
    - Downgrading removes the businesses table and every user's business
      assignment; it is lossless only while all users belong to legacy.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '652cc0a22e68'
down_revision: Union[str, Sequence[str], None] = '32721ce95d01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_SLUG = "legacy"
LEGACY_NAME = "Legacy"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'businesses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=63), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name='pk_businesses'),
        sa.UniqueConstraint('slug', name='uq_businesses_slug'),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name='ck_businesses_slug_format',
        ),
    )

    legacy_id = op.get_bind().execute(
        sa.text(
            "INSERT INTO businesses (name, slug) "
            "VALUES (:name, :slug) RETURNING id"
        ),
        {"name": LEGACY_NAME, "slug": LEGACY_SLUG},
    ).scalar_one()

    # Allow missing business IDs until existing users have been assigned to Legacy.
    op.add_column(
        'users',
        sa.Column('business_id', sa.Integer(), nullable=True),
    )

    op.get_bind().execute(
        sa.text("UPDATE users SET business_id = :legacy_id"),
        {"legacy_id": legacy_id},
    )

    op.alter_column('users', 'business_id', nullable=False)

    op.create_foreign_key(
        'fk_users_business_id_businesses',
        'users',
        'businesses',
        ['business_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.create_index(
        'ix_users_business_id',
        'users',
        ['business_id'],
        unique=False,
    )

    # The old app does not send business_id, so assign its new users to Legacy
    # until public registration is closed and this default is removed.
    # PostgreSQL defaults cannot contain subqueries, so the id is a literal.
    op.alter_column(
        'users',
        'business_id',
        server_default=sa.text(str(int(legacy_id))),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_users_business_id_businesses',
        'users',
        type_='foreignkey',
    )
    op.drop_index('ix_users_business_id', table_name='users')
    op.drop_column('users', 'business_id')
    op.drop_table('businesses')
