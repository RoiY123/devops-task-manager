import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
TASK_VISIBILITY = "b840ad91c0f4"
TASK_GRANTS = "abfef75f2975"


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


def add_grant(
    connection: Connection,
    viewer_id: int,
    owner_id: int,
    business_id: int,
    permission: str = "view",
) -> None:
    connection.execute(
        text(
            "INSERT INTO task_grants (viewer_id, owner_id, business_id, permission) "
            "VALUES (:viewer_id, :owner_id, :business_id, :permission)"
        ),
        {
            "viewer_id": viewer_id,
            "owner_id": owner_id,
            "business_id": business_id,
            "permission": permission,
        },
    )


def grant_count(connection: Connection) -> int:
    return connection.execute(text("SELECT count(*) FROM task_grants")).scalar_one()


@pytest.fixture
def people(alembic_config: Config, engine: Engine) -> dict[str, int]:
    """After upgrading to TASK_GRANTS: Avi and Noa in 'first', Boss in 'second'."""
    command.upgrade(alembic_config, TASK_GRANTS)

    with engine.begin() as connection:
        first = add_business(connection, "first")
        second = add_business(connection, "second")
        return {
            "first": first,
            "second": second,
            "avi": add_user(connection, "avi@example.com", first),
            "noa": add_user(connection, "noa@example.com", first),
            "boss": add_user(connection, "boss@example.com", second),
        }


@pytest.mark.parametrize(
    ("grant", "constraint"),
    [
        # A viewer from another business, under either business's id.
        (("boss", "avi", "first", "view"), "fk_task_grants_business_id_viewer_id_users"),
        (("boss", "avi", "second", "view"), "fk_task_grants_business_id_owner_id_users"),
        (("avi", "avi", "first", "view"), "ck_task_grants_not_self"),
        (("noa", "avi", "first", "edit"), "ck_task_grants_permission"),
    ],
)
def test_database_refuses_invalid_grants(
    engine: Engine,
    people: dict[str, int],
    grant: tuple[str, str, str, str],
    constraint: str,
) -> None:
    viewer, owner, business, permission = grant

    with pytest.raises(IntegrityError, match=constraint):
        with engine.begin() as connection:
            add_grant(
                connection, people[viewer], people[owner], people[business], permission
            )


def test_deleting_a_user_deletes_their_grants(
    engine: Engine,
    people: dict[str, int],
) -> None:
    with engine.begin() as connection:
        add_grant(connection, people["noa"], people["avi"], people["first"])
        connection.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": people["avi"]}
        )

        assert grant_count(connection) == 0


def test_downgrade_drops_grants_then_upgrade_again(
    alembic_config: Config,
    engine: Engine,
    people: dict[str, int],
) -> None:
    with engine.begin() as connection:
        add_grant(connection, people["noa"], people["avi"], people["first"])

    command.downgrade(alembic_config, TASK_VISIBILITY)

    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT to_regclass('task_grants')")
        ).scalar() is None

    command.upgrade(alembic_config, TASK_GRANTS)

    with engine.begin() as connection:
        assert grant_count(connection) == 0
