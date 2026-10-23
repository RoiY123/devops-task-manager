import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
ADD_BUSINESSES = "652cc0a22e68"
ADD_USER_ROLES = "d217ba767047"

SEED_EMAILS = ["alice@example.com", "bob@example.com"]


def seed_users(connection: Connection) -> None:
    # Inserted the way the application before this migration does it:
    # no role column, business_id filled by the legacy default.
    for email in SEED_EMAILS:
        connection.execute(
            text(
                "INSERT INTO users (email, hashed_password) "
                "VALUES (:email, :hashed_password)"
            ),
            {"email": email, "hashed_password": f"hash-{email}"},
        )


def snapshot_users(connection: Connection) -> list[tuple]:
    rows = connection.execute(
        text(
            "SELECT id, email, hashed_password, business_id "
            "FROM users ORDER BY id"
        )
    ).all()

    return [tuple(row) for row in rows]


def user_roles(connection: Connection) -> set[str]:
    return set(connection.execute(text("SELECT role FROM users")).scalars())


def test_upgrade_makes_existing_users_members(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_BUSINESSES)

    with engine.begin() as connection:
        seed_users(connection)
        before = snapshot_users(connection)

    command.upgrade(alembic_config, ADD_USER_ROLES)

    with engine.begin() as connection:
        assert snapshot_users(connection) == before

        # Existing production accounts must not gain admin rights.
        assert user_roles(connection) == {"member"}

        # The previous app version inserts users without a role.
        old_app_role = connection.execute(
            text(
                "INSERT INTO users (email, hashed_password) "
                "VALUES ('old-app@example.com', 'hash-old-app') "
                "RETURNING role"
            )
        ).scalar_one()

    assert old_app_role == "member"


def test_database_rejects_unknown_role(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_USER_ROLES)

    with pytest.raises(IntegrityError, match="ck_users_role"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (email, hashed_password, role) "
                    "VALUES ('owner@example.com', 'hash-owner', 'owner')"
                )
            )


def test_downgrade_then_upgrade_round_trip(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_USER_ROLES)

    # Members only: a downgrade discards roles, so admins would not survive it.
    with engine.begin() as connection:
        seed_users(connection)
        before = snapshot_users(connection)

    command.downgrade(alembic_config, ADD_BUSINESSES)

    inspector = inspect(engine)
    assert "role" not in {
        column["name"] for column in inspector.get_columns("users")
    }
    assert "ck_users_role" not in {
        constraint["name"]
        for constraint in inspector.get_check_constraints("users")
    }

    with engine.begin() as connection:
        assert snapshot_users(connection) == before

    command.upgrade(alembic_config, ADD_USER_ROLES)

    with engine.begin() as connection:
        assert snapshot_users(connection) == before
        assert user_roles(connection) == {"member"}
