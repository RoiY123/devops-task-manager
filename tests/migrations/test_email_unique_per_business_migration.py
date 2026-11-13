import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError


# Explicit revisions (not "head") keep these tests valid after later migrations.
ADD_APP_ROLE = "670248a338cd"
PER_BUSINESS_EMAIL = "586fecaea66f"


def add_business(connection: Connection, slug: str) -> int:
    return connection.execute(
        text("INSERT INTO businesses (name, slug) VALUES (:slug, :slug) RETURNING id"),
        {"slug": slug},
    ).scalar_one()


def add_user(connection: Connection, email: str, business_id: int) -> None:
    connection.execute(
        text(
            "INSERT INTO users (email, hashed_password, business_id) "
            "VALUES (:email, 'hash', :business_id)"
        ),
        {"email": email, "business_id": business_id},
    )


def users_indexes(connection: Connection) -> set[str]:
    return set(
        connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'users'")
        ).scalars()
    )


def snapshot_users(connection: Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            text("SELECT id, email, hashed_password, business_id FROM users ORDER BY id")
        )
    ]


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_upgrade_keeps_users_and_scopes_emails_to_a_business(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_APP_ROLE)

    with engine.begin() as connection:
        first = add_business(connection, "first")
        second = add_business(connection, "second")
        add_user(connection, "dana@example.com", first)
        add_user(connection, "Avi@example.com", second)
        before = snapshot_users(connection)

    command.upgrade(alembic_config, PER_BUSINESS_EMAIL)

    with engine.begin() as connection:
        assert snapshot_users(connection) == before
        indexes = users_indexes(connection)
        assert "uq_users_business_id_lower_email" in indexes
        assert "ix_users_email" not in indexes

        # Allowed now: the same email in another business.
        add_user(connection, "dana@example.com", second)

    # Refused: the same email, in other capitals, in the same business.
    with pytest.raises(IntegrityError, match="uq_users_business_id_lower_email"):
        with engine.begin() as connection:
            add_user(connection, "AVI@example.com", second)


def test_downgrade_restores_global_uniqueness_then_upgrade_again(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, PER_BUSINESS_EMAIL)

    with engine.begin() as connection:
        add_user(connection, "dana@example.com", add_business(connection, "first"))

    command.downgrade(alembic_config, ADD_APP_ROLE)

    with engine.begin() as connection:
        indexes = users_indexes(connection)
        assert "ix_users_email" in indexes
        assert "uq_users_business_id_lower_email" not in indexes

    command.upgrade(alembic_config, PER_BUSINESS_EMAIL)

    with engine.begin() as connection:
        assert "uq_users_business_id_lower_email" in users_indexes(connection)


def test_downgrade_is_refused_while_an_email_is_shared(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, PER_BUSINESS_EMAIL)

    with engine.begin() as connection:
        add_user(connection, "dana@example.com", add_business(connection, "first"))
        add_user(connection, "dana@example.com", add_business(connection, "second"))

    with pytest.raises(RuntimeError, match="1 email\\(s\\) exist in more than one business"):
        command.downgrade(alembic_config, ADD_APP_ROLE)

    # Nothing changed: same revision, and the per-business rule still applies.
    assert current_revision(engine) == PER_BUSINESS_EMAIL
    with engine.begin() as connection:
        assert "uq_users_business_id_lower_email" in users_indexes(connection)
