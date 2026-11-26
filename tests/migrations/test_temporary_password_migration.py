import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text


# Explicit revisions (not "head") keep these tests valid after later migrations.
TOKENS_VALID_AFTER = "f44f6b069ec6"
TEMPORARY_PASSWORD = "74ff2b7630c0"


@pytest.fixture
def business_id(alembic_config: Config, engine: Engine) -> int:
    """A business in a database from before this migration."""
    command.upgrade(alembic_config, TOKENS_VALID_AFTER)
    with engine.begin() as connection:
        return connection.execute(
            text("INSERT INTO businesses (name, slug) VALUES ('Shop', 'shop') RETURNING id")
        ).scalar_one()


def add_user(connection: Connection, email: str, business_id: int) -> int:
    # Without the new column: the insert the app version before this migration sends.
    return connection.execute(
        text(
            "INSERT INTO users (email, hashed_password, business_id) "
            "VALUES (:email, 'hash', :business_id) RETURNING id"
        ),
        {"email": email, "business_id": business_id},
    ).scalar_one()


def expiry(connection: Connection, user_id: int):
    return connection.execute(
        text("SELECT temporary_password_expires_at FROM users WHERE id = :id"),
        {"id": user_id},
    ).scalar_one()


def test_existing_and_old_app_users_have_normal_passwords(
    alembic_config: Config, engine: Engine, business_id: int
) -> None:
    with engine.begin() as connection:
        dana = add_user(connection, "dana@example.com", business_id)

    command.upgrade(alembic_config, TEMPORARY_PASSWORD)

    with engine.begin() as connection:
        avi = add_user(connection, "avi@example.com", business_id)
        assert expiry(connection, dana) is None
        assert expiry(connection, avi) is None


def test_app_role_can_set_and_clear_the_expiry(
    alembic_config: Config, engine: Engine, business_id: int
) -> None:
    command.upgrade(alembic_config, TEMPORARY_PASSWORD)

    with engine.begin() as connection:
        dana = add_user(connection, "dana@example.com", business_id)
        # The permissions the application really has; postgres may switch to them.
        connection.execute(text("SET ROLE task_manager_app"))
        for value, is_set in (("now()", True), ("NULL", False)):
            connection.execute(
                text(f"UPDATE users SET temporary_password_expires_at = {value} WHERE id = :id"),
                {"id": dana},
            )
            assert (expiry(connection, dana) is not None) is is_set


def test_downgrade_keeps_the_user_and_forgets_the_expiry(
    alembic_config: Config, engine: Engine, business_id: int
) -> None:
    command.upgrade(alembic_config, TEMPORARY_PASSWORD)
    with engine.begin() as connection:
        dana = add_user(connection, "dana@example.com", business_id)
        connection.execute(text("UPDATE users SET temporary_password_expires_at = now()"))

    command.downgrade(alembic_config, TOKENS_VALID_AFTER)
    command.upgrade(alembic_config, TEMPORARY_PASSWORD)

    with engine.begin() as connection:
        assert expiry(connection, dana) is None
