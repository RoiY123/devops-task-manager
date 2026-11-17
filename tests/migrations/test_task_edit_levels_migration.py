import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
BUSINESS_LEADER = "f4c26d7e2c28"
EDIT_LEVELS = "933faab25aed"


def add_business(connection: Connection, slug: str) -> int:
    return connection.execute(
        text("INSERT INTO businesses (name, slug) VALUES (:slug, :slug) RETURNING id"),
        {"slug": slug},
    ).scalar_one()


def add_user(
    connection: Connection,
    email: str,
    business_id: int,
    role: str = "member",
    sees_all: bool = False,
) -> int:
    # Without edits_all_tasks: the insert the app version before this migration sends.
    return connection.execute(
        text(
            "INSERT INTO users (email, hashed_password, business_id, role, sees_all_tasks) "
            "VALUES (:email, 'hash', :business_id, :role, :sees_all) RETURNING id"
        ),
        {"email": email, "business_id": business_id, "role": role, "sees_all": sees_all},
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


def grant_rows(connection: Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            text("SELECT viewer_id, owner_id, permission FROM task_grants ORDER BY viewer_id")
        )
    ]


def user_value(connection: Connection, user_id: int, column: str):
    return connection.execute(
        text(f"SELECT {column} FROM users WHERE id = :id"), {"id": user_id}
    ).scalar_one()


def user_columns(connection: Connection) -> set[str]:
    return set(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'users'"
            )
        ).scalars()
    )


def test_upgrade_makes_admins_see_all_and_drops_grants_that_had_no_effect(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, BUSINESS_LEADER)

    with engine.begin() as connection:
        shop = add_business(connection, "shop")
        # An admin limited to own tasks, which the new rules forbid.
        eli = add_user(connection, "eli@example.com", shop, "admin", sees_all=False)
        avi = add_user(connection, "avi@example.com", shop)
        # Sees all and has a grant: the grant added nothing.
        noa = add_user(connection, "noa@example.com", shop, sees_all=True)
        # Own tasks plus a grant: the grant matters.
        zoe = add_user(connection, "zoe@example.com", shop)
        add_grant(connection, noa, avi, shop)
        add_grant(connection, zoe, avi, shop)

    command.upgrade(alembic_config, EDIT_LEVELS)

    with engine.begin() as connection:
        assert user_value(connection, eli, "sees_all_tasks") is True
        assert grant_rows(connection) == [(zoe, avi, "view")]
        assert user_value(connection, zoe, "edits_all_tasks") is False


@pytest.fixture
def shop(alembic_config: Config, engine: Engine) -> dict[str, int]:
    """After upgrading: an admin, a member who sees own tasks, and a view grant."""
    command.upgrade(alembic_config, EDIT_LEVELS)

    with engine.begin() as connection:
        shop = add_business(connection, "shop")
        eli = add_user(connection, "eli@example.com", shop, "admin", sees_all=True)
        avi = add_user(connection, "avi@example.com", shop)
        add_grant(connection, avi, eli, shop)
        return {"shop": shop, "eli": eli, "avi": avi}


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "UPDATE users SET sees_all_tasks = false WHERE role = 'admin'",
            "ck_users_admin_sees_all",
        ),
        (
            "UPDATE users SET edits_all_tasks = true WHERE role = 'member'",
            "ck_users_edits_all_needs_sees_all",
        ),
        ("UPDATE task_grants SET permission = 'delete'", "ck_task_grants_permission"),
    ],
)
def test_database_refuses_settings_that_break_the_rules(
    engine: Engine,
    shop: dict[str, int],
    statement: str,
    constraint: str,
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        with engine.begin() as connection:
            connection.execute(text(statement))


def test_old_app_inserts_still_work_and_edit_grants_are_allowed(
    engine: Engine,
    shop: dict[str, int],
) -> None:
    with engine.begin() as connection:
        noa = add_user(connection, "noa@example.com", shop["shop"])
        add_grant(connection, noa, shop["avi"], shop["shop"], "edit")

        assert user_value(connection, noa, "edits_all_tasks") is False
        assert (noa, shop["avi"], "edit") in grant_rows(connection)


def test_downgrade_turns_edit_grants_into_view_grants_then_upgrade_again(
    alembic_config: Config,
    engine: Engine,
    shop: dict[str, int],
) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE task_grants SET permission = 'edit'"))

    command.downgrade(alembic_config, BUSINESS_LEADER)

    with engine.begin() as connection:
        assert grant_rows(connection) == [(shop["avi"], shop["eli"], "view")]
        assert "edits_all_tasks" not in user_columns(connection)

    command.upgrade(alembic_config, EDIT_LEVELS)

    with engine.begin() as connection:
        assert grant_rows(connection) == [(shop["avi"], shop["eli"], "view")]
