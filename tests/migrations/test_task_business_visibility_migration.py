import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
PER_BUSINESS_EMAIL = "586fecaea66f"
TASK_VISIBILITY = "b840ad91c0f4"


def add_business(connection: Connection, slug: str) -> int:
    return connection.execute(
        text("INSERT INTO businesses (name, slug) VALUES (:slug, :slug) RETURNING id"),
        {"slug": slug},
    ).scalar_one()


def add_user(
    connection: Connection, email: str, business_id: int, role: str = "member"
) -> int:
    return connection.execute(
        text(
            "INSERT INTO users (email, hashed_password, business_id, role) "
            "VALUES (:email, 'hash', :business_id, :role) RETURNING id"
        ),
        {"email": email, "business_id": business_id, "role": role},
    ).scalar_one()


def add_task_like_old_app(connection: Connection, owner_id: int) -> int:
    # The insert the app version before this migration sends: no business_id.
    return connection.execute(
        text(
            "INSERT INTO tasks (title, completed, owner_id) "
            "VALUES ('משימה', false, :owner_id) RETURNING id"
        ),
        {"owner_id": owner_id},
    ).scalar_one()


def task_business(connection: Connection, task_id: int) -> int:
    return connection.execute(
        text("SELECT business_id FROM tasks WHERE id = :id"), {"id": task_id}
    ).scalar_one()


def test_upgrade_gives_tasks_their_owners_business_and_admins_all_tasks(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, PER_BUSINESS_EMAIL)

    with engine.begin() as connection:
        first = add_business(connection, "first")
        second = add_business(connection, "second")
        dana = add_user(connection, "dana@example.com", first, role="admin")
        avi = add_user(connection, "avi@example.com", second)
        dana_task = add_task_like_old_app(connection, dana)
        avi_task = add_task_like_old_app(connection, avi)

    command.upgrade(alembic_config, TASK_VISIBILITY)

    with engine.begin() as connection:
        assert task_business(connection, dana_task) == first
        assert task_business(connection, avi_task) == second
        sees_all = dict(
            connection.execute(text("SELECT email, sees_all_tasks FROM users")).all()
        )
        assert sees_all == {"dana@example.com": True, "avi@example.com": False}


def test_old_app_inserts_are_filled_and_mismatched_businesses_refused(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, TASK_VISIBILITY)

    with engine.begin() as connection:
        first = add_business(connection, "first")
        second = add_business(connection, "second")
        avi = add_user(connection, "avi@example.com", first)
        assert task_business(connection, add_task_like_old_app(connection, avi)) == first

    with pytest.raises(IntegrityError, match="fk_tasks_business_id_owner_id_users"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO tasks (title, completed, owner_id, business_id) "
                    "VALUES ('x', false, :owner_id, :business_id)"
                ),
                {"owner_id": avi, "business_id": second},
            )


def test_downgrade_removes_the_changes_then_upgrade_again(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, TASK_VISIBILITY)

    with engine.begin() as connection:
        first = add_business(connection, "first")
        avi = add_user(connection, "avi@example.com", first)

    command.downgrade(alembic_config, PER_BUSINESS_EMAIL)

    with engine.begin() as connection:
        columns = set(
            connection.execute(
                text(
                    "SELECT table_name || '.' || column_name "
                    "FROM information_schema.columns "
                    "WHERE table_name IN ('tasks', 'users')"
                )
            ).scalars()
        )
        assert {"tasks.business_id", "users.sees_all_tasks"}.isdisjoint(columns)
        # The function cannot be dropped while a trigger still uses it,
        # so its absence shows the trigger is gone too.
        assert connection.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'tasks_fill_business_id'")
        ).scalar_one() == 0
        task_id = add_task_like_old_app(connection, avi)

    command.upgrade(alembic_config, TASK_VISIBILITY)

    with engine.begin() as connection:
        assert task_business(connection, task_id) == first
