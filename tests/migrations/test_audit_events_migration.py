import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError


# Explicit revisions (not "head") keep these tests valid after later migrations.
EDIT_LEVELS = "933faab25aed"
AUDIT_EVENTS = "0496b5c9c61f"

INSERT = (
    "INSERT INTO audit_events (business_id, business_slug, actor_kind, action) "
    "VALUES (1, 'shop', 'operator', 'business_created')"
)


def as_app_role(connection: Connection) -> None:
    # The permissions the application really has; postgres may switch to them.
    connection.execute(text("SET ROLE task_manager_app"))


def table_exists(connection: Connection) -> bool:
    return connection.execute(text("SELECT to_regclass('audit_events')")).scalar() is not None


def test_app_role_may_add_and_read_events(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, AUDIT_EVENTS)

    with engine.begin() as connection:
        as_app_role(connection)
        connection.execute(text(INSERT))
        assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'rewritten'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
def test_app_role_cannot_change_or_erase_history(
    alembic_config: Config,
    engine: Engine,
    statement: str,
) -> None:
    command.upgrade(alembic_config, AUDIT_EVENTS)
    with engine.begin() as connection:
        connection.execute(text(INSERT))

    with pytest.raises(ProgrammingError, match="permission denied for table audit_events"):
        with engine.begin() as connection:
            as_app_role(connection)
            connection.execute(text(statement))

    # The event is untouched.
    with engine.begin() as connection:
        assert (
            connection.execute(text("SELECT action FROM audit_events")).scalar_one()
            == "business_created"
        )


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ("'bot', NULL, NULL", "ck_audit_events_actor_kind"),
        # A user event without its email.
        ("'user', 7, NULL", "ck_audit_events_actor"),
        # An operator event naming a user.
        ("'operator', 7, 'dana@example.com'", "ck_audit_events_actor"),
    ],
)
def test_database_refuses_events_with_an_unclear_actor(
    alembic_config: Config,
    engine: Engine,
    values: str,
    constraint: str,
) -> None:
    command.upgrade(alembic_config, AUDIT_EVENTS)

    with pytest.raises(IntegrityError, match=constraint):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_events (business_id, business_slug, actor_kind, "
                    f"actor_user_id, actor_email, action) VALUES (1, 'shop', {values}, 'x')"
                )
            )


def test_downgrade_removes_the_table_then_upgrade_again(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, AUDIT_EVENTS)
    with engine.begin() as connection:
        connection.execute(text(INSERT))

    command.downgrade(alembic_config, EDIT_LEVELS)

    with engine.begin() as connection:
        assert not table_exists(connection)

    command.upgrade(alembic_config, AUDIT_EVENTS)

    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0
        connection.execute(text(INSERT))

    # The re-created table is append-only for the app role too.
    with pytest.raises(ProgrammingError, match="permission denied for table audit_events"):
        with engine.begin() as connection:
            as_app_role(connection)
            connection.execute(text("DELETE FROM audit_events"))
