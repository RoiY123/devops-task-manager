"""add business leader

Revision ID: f4c26d7e2c28
Revises: 2bd7ae5baabe
Create Date: 2026-11-15 16:03:58.972189

Adds businesses.leader_user_id: the business's leader, one of its own admins.
Empty only for a business without users. Each existing business with users
gets its earliest admin (lowest id, normally the onboarding admin) as leader.

The composite foreign key keeps the leader inside the business and refuses
deleting a user while they are recorded as leader.

Rollback restrictions:
    - Images built before this migration ignore the leader: their set-role can
      demote the leader and their create-business leaves the leader empty;
      transfer-leadership in a newer image repairs either. Removing the
      leader is refused by the foreign key in every image.
    - Downgrading forgets who the leader was; that user stays an admin.

General procedure: "Database compatibility and rollback" in
docs/deployment.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4c26d7e2c28'
down_revision: Union[str, Sequence[str], None] = '2bd7ae5baabe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()
    # The app keeps an admin in every business with users,
    # but the database alone does not; stop rather than pick a leader from members.
    leaderless = connection.execute(
        sa.text(
            "SELECT count(*) FROM businesses b "
            "WHERE EXISTS (SELECT 1 FROM users u WHERE u.business_id = b.id) "
            "AND NOT EXISTS (SELECT 1 FROM users u "
            "WHERE u.business_id = b.id AND u.role = 'admin')"
        )
    ).scalar_one()
    if leaderless:
        raise RuntimeError(
            f"{leaderless} business(es) have users but no admin; "
            "promote an admin in each, then retry"
        )

    op.add_column('businesses', sa.Column('leader_user_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE businesses SET leader_user_id = ("
        "SELECT min(id) FROM users "
        "WHERE users.business_id = businesses.id AND users.role = 'admin')"
    )
    op.create_foreign_key(
        'fk_businesses_id_leader_user_id_users',
        'businesses',
        'users',
        ['id', 'leader_user_id'],
        ['business_id', 'id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_businesses_id_leader_user_id_users', 'businesses', type_='foreignkey'
    )
    op.drop_column('businesses', 'leader_user_id')
