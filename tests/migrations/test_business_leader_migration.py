import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
DROP_TRIGGER = "2bd7ae5baabe"
BUSINESS_LEADER = "f4c26d7e2c28"


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


def set_leader(connection: Connection, business_id: int, user_id: int) -> None:
    connection.execute(
        text("UPDATE businesses SET leader_user_id = :user_id WHERE id = :id"),
        {"user_id": user_id, "id": business_id},
    )


def leader_of(connection: Connection, business_id: int) -> int | None:
    return connection.execute(
        text("SELECT leader_user_id FROM businesses WHERE id = :id"),
        {"id": business_id},
    ).scalar_one()


def business_columns(connection: Connection) -> set[str]:
    return set(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'businesses'"
            )
        ).scalars()
    )


def user_role(connection: Connection, user_id: int) -> str:
    return connection.execute(
        text("SELECT role FROM users WHERE id = :id"), {"id": user_id}
    ).scalar_one()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_upgrade_makes_the_earliest_admin_the_leader(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, DROP_TRIGGER)

    with engine.begin() as connection:
        shop = add_business(connection, "shop")
        empty = add_business(connection, "empty")
        # A member first by id: the leader must be the earliest admin, not user.
        add_user(connection, "avi@example.com", shop)
        dana = add_user(connection, "dana@example.com", shop, "admin")
        add_user(connection, "eli@example.com", shop, "admin")

    command.upgrade(alembic_config, BUSINESS_LEADER)

    with engine.begin() as connection:
        assert leader_of(connection, shop) == dana
        assert leader_of(connection, empty) is None


def test_upgrade_stops_when_a_business_has_users_but_no_admin(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, DROP_TRIGGER)

    with engine.begin() as connection:
        add_user(connection, "avi@example.com", add_business(connection, "shop"))

    with pytest.raises(RuntimeError, match="1 business\\(es\\) have users but no admin"):
        command.upgrade(alembic_config, BUSINESS_LEADER)

    # Nothing changed: still the previous revision.
    assert current_revision(engine) == DROP_TRIGGER


@pytest.mark.parametrize("action", ["leader from another business", "delete the leader"])
def test_foreign_key_keeps_the_leader_in_the_business(
    alembic_config: Config,
    engine: Engine,
    action: str,
) -> None:
    command.upgrade(alembic_config, BUSINESS_LEADER)

    with engine.begin() as connection:
        shop = add_business(connection, "shop")
        other = add_business(connection, "other")
        dana = add_user(connection, "dana@example.com", shop, "admin")
        boss = add_user(connection, "boss@example.com", other, "admin")
        set_leader(connection, shop, dana)

    with pytest.raises(IntegrityError, match="fk_businesses_id_leader_user_id_users"):
        with engine.begin() as connection:
            if action == "leader from another business":
                set_leader(connection, shop, boss)
            else:
                connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": dana})


def test_downgrade_forgets_the_leader_then_upgrade_again(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, BUSINESS_LEADER)

    with engine.begin() as connection:
        shop = add_business(connection, "shop")
        dana = add_user(connection, "dana@example.com", shop, "admin")
        set_leader(connection, shop, dana)

    command.downgrade(alembic_config, DROP_TRIGGER)

    with engine.begin() as connection:
        assert "leader_user_id" not in business_columns(connection)
        # The leader stays an admin.
        assert user_role(connection, dana) == "admin"

    command.upgrade(alembic_config, BUSINESS_LEADER)

    with engine.begin() as connection:
        # Backfilled again.
        assert leader_of(connection, shop) == dana
