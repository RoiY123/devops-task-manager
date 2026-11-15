import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
TASK_GRANTS = "abfef75f2975"
DROP_TRIGGER = "2bd7ae5baabe"


def add_business(connection: Connection, slug: str) -> int:
    return connection.execute(
        text("INSERT INTO businesses (name, slug) VALUES (:slug, :slug) RETURNING id"),
        {"slug": slug},
    ).scalar_one()


def add_user(connection: Connection, email: str, business_id: int) -> int:
    return connection.execute(
        text(
            "INSERT INTO users (email, hashed_password, business_id) "
            "VALUES (:email, 'hash', :business_id) RETURNING id"
        ),
        {"email": email, "business_id": business_id},
    ).scalar_one()


def add_task_without_business(connection: Connection, owner_id: int) -> int:
    # What an image from before b840ad91c0f4 sends: no business_id.
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


def test_insert_without_business_is_refused_until_downgrade(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, DROP_TRIGGER)

    with engine.begin() as connection:
        business = add_business(connection, "first")
        avi = add_user(connection, "avi@example.com", business)

    with pytest.raises(IntegrityError, match='null value in column "business_id"'):
        with engine.begin() as connection:
            add_task_without_business(connection, avi)

    command.downgrade(alembic_config, TASK_GRANTS)

    with engine.begin() as connection:
        task_id = add_task_without_business(connection, avi)
        assert task_business(connection, task_id) == business
