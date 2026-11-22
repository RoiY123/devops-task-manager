from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text


# Explicit revisions (not "head") keep these tests valid after later migrations.
AUDIT_EVENTS = "0496b5c9c61f"
TOKENS_VALID_AFTER = "f44f6b069ec6"


def add_user(connection: Connection, email: str) -> int:
    # Without tokens_valid_after: the insert the app version before this migration sends.
    business = connection.execute(
        text("INSERT INTO businesses (name, slug) VALUES ('Shop', 'shop') RETURNING id")
    ).scalar_one()
    return connection.execute(
        text(
            "INSERT INTO users (email, hashed_password, business_id) "
            "VALUES (:email, 'hash', :business) RETURNING id"
        ),
        {"email": email, "business": business},
    ).scalar_one()


def cut_off(connection: Connection, user_id: int):
    return connection.execute(
        text("SELECT tokens_valid_after FROM users WHERE id = :id"), {"id": user_id}
    ).scalar_one()


def test_existing_users_get_no_cut_off_and_old_inserts_still_work(
    alembic_config: Config, engine: Engine
) -> None:
    command.upgrade(alembic_config, AUDIT_EVENTS)
    with engine.begin() as connection:
        dana = add_user(connection, "dana@example.com")

    command.upgrade(alembic_config, TOKENS_VALID_AFTER)

    with engine.begin() as connection:
        assert cut_off(connection, dana) is None
        avi = connection.execute(
            text(
                "INSERT INTO users (email, hashed_password, business_id) "
                "SELECT 'avi@example.com', 'hash', business_id FROM users "
                "WHERE id = :id RETURNING id"
            ),
            {"id": dana},
        ).scalar_one()
        assert cut_off(connection, avi) is None


def test_app_role_can_set_the_cut_off(alembic_config: Config, engine: Engine) -> None:
    command.upgrade(alembic_config, TOKENS_VALID_AFTER)

    with engine.begin() as connection:
        dana = add_user(connection, "dana@example.com")
        # The permissions the application really has; postgres may switch to them.
        connection.execute(text("SET ROLE task_manager_app"))
        connection.execute(
            text("UPDATE users SET tokens_valid_after = now() WHERE id = :id"), {"id": dana}
        )
        assert cut_off(connection, dana) is not None


def test_downgrade_drops_the_column_then_upgrade_again(
    alembic_config: Config, engine: Engine
) -> None:
    command.upgrade(alembic_config, TOKENS_VALID_AFTER)
    with engine.begin() as connection:
        dana = add_user(connection, "dana@example.com")
        connection.execute(text("UPDATE users SET tokens_valid_after = now()"))

    command.downgrade(alembic_config, AUDIT_EVENTS)
    command.upgrade(alembic_config, TOKENS_VALID_AFTER)

    with engine.begin() as connection:
        assert cut_off(connection, dana) is None
