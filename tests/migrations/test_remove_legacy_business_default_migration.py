import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
ADD_USER_ROLES = "d217ba767047"
REMOVE_DEFAULT = "46c6a6bfb8b4"


def legacy_business_id(connection: Connection) -> int:
    return connection.execute(
        text("SELECT id FROM businesses WHERE slug = 'legacy'")
    ).scalar_one()


def insert_user_without_business(connection: Connection, email: str) -> int:
    return connection.execute(
        text(
            "INSERT INTO users (email, hashed_password) "
            "VALUES (:email, 'hash') RETURNING business_id"
        ),
        {"email": email},
    ).scalar_one()


def snapshot_users(connection: Connection) -> list[tuple]:
    rows = connection.execute(
        text(
            "SELECT id, email, hashed_password, business_id, role "
            "FROM users ORDER BY id"
        )
    ).all()

    return [tuple(row) for row in rows]


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_upgrade_keeps_users_and_rejects_missing_business(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_USER_ROLES)

    with engine.begin() as connection:
        insert_user_without_business(connection, "alice@example.com")
        insert_user_without_business(connection, "bob@example.com")
        before = snapshot_users(connection)

    command.upgrade(alembic_config, REMOVE_DEFAULT)

    with engine.begin() as connection:
        assert snapshot_users(connection) == before

    with pytest.raises(IntegrityError, match="business_id"):
        with engine.begin() as connection:
            insert_user_without_business(connection, "nobody@example.com")

    # The application version serving during the deploy sets business_id itself.
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (email, hashed_password, business_id) "
                "VALUES ('explicit@example.com', 'hash', :business_id)"
            ),
            {"business_id": legacy_business_id(connection)},
        )


def test_downgrade_restores_default_then_upgrade_removes_it(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_USER_ROLES)

    with engine.begin() as connection:
        insert_user_without_business(connection, "alice@example.com")

    command.upgrade(alembic_config, REMOVE_DEFAULT)

    with engine.begin() as connection:
        before = snapshot_users(connection)

    command.downgrade(alembic_config, ADD_USER_ROLES)

    with engine.begin() as connection:
        assert snapshot_users(connection) == before

        restored_business_id = insert_user_without_business(
            connection, "after-downgrade@example.com"
        )
        assert restored_business_id == legacy_business_id(connection)

        connection.execute(
            text("DELETE FROM users WHERE email = 'after-downgrade@example.com'")
        )

    command.upgrade(alembic_config, REMOVE_DEFAULT)

    with engine.begin() as connection:
        assert snapshot_users(connection) == before

    with pytest.raises(IntegrityError, match="business_id"):
        with engine.begin() as connection:
            insert_user_without_business(connection, "nobody@example.com")


def test_downgrade_without_legacy_business_changes_nothing(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, REMOVE_DEFAULT)

    # A fresh database has an empty legacy business, so it can be removed.
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM businesses WHERE slug = 'legacy'"))

    with pytest.raises(RuntimeError, match="legacy business is missing"):
        command.downgrade(alembic_config, ADD_USER_ROLES)

    # The failed downgrade ran in a transaction, so the schema is unchanged.
    assert current_revision(engine) == REMOVE_DEFAULT
