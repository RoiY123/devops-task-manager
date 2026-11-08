import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import ProgrammingError


# Explicit revisions (not "head") keep these tests valid after later migrations.
REMOVE_LEGACY_DEFAULT = "46c6a6bfb8b4"
ADD_APP_ROLE = "670248a338cd"

APP_ROLE = "task_manager_app"
DATA_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE")


def app_tables(connection: Connection) -> list[str]:
    return list(
        connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version' "
                "ORDER BY tablename"
            )
        ).scalars()
    )


def table_privileges(connection: Connection, table: str) -> dict[str, bool]:
    return {
        privilege: connection.execute(
            text("SELECT has_table_privilege(:role, :table, :privilege)"),
            {"role": APP_ROLE, "table": f"public.{table}", "privilege": privilege},
        ).scalar_one()
        for privilege in DATA_PRIVILEGES
    }


def sequences_usable(connection: Connection) -> dict[str, bool]:
    return dict(
        connection.execute(
            text(
                "SELECT sequencename, has_sequence_privilege(:role, "
                "'public.' || sequencename, 'USAGE') "
                "FROM pg_sequences WHERE schemaname = 'public'"
            ),
            {"role": APP_ROLE},
        ).all()
    )


def run_as_app_role(engine: Engine, statement: str) -> None:
    # SET ROLE lasts only for this transaction, which is always rolled back.
    with engine.connect() as connection:
        with connection.begin() as transaction:
            connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
            try:
                connection.execute(text(statement))
            finally:
                transaction.rollback()


def test_app_role_gets_data_access_but_cannot_change_the_schema(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_APP_ROLE)

    with engine.connect() as connection:
        tables = app_tables(connection)
        assert tables  # guards against checking nothing

        for table in tables:
            assert table_privileges(connection, table) == dict.fromkeys(
                DATA_PRIVILEGES, True
            ), table

        assert table_privileges(connection, "alembic_version") == {
            "SELECT": True,
            "INSERT": False,
            "UPDATE": False,
            "DELETE": False,
        }

        sequences = sequences_usable(connection)
        assert sequences and all(sequences.values()), sequences

    # Exercise the real restrictions, not only the privilege catalog.
    with pytest.raises(ProgrammingError, match="permission denied"):
        run_as_app_role(engine, "CREATE TABLE intruder (id integer)")

    with pytest.raises(ProgrammingError, match="must be owner"):
        run_as_app_role(engine, "DROP TABLE tasks")

    with pytest.raises(ProgrammingError, match="must be owner"):
        run_as_app_role(engine, "ALTER TABLE users ADD COLUMN extra integer")

    with pytest.raises(ProgrammingError, match="permission denied"):
        run_as_app_role(engine, "UPDATE alembic_version SET version_num = 'x'")


def test_tables_created_by_later_migrations_get_the_same_access(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_APP_ROLE)

    # Stands in for a future migration run by the same migration user.
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE future_table (id serial PRIMARY KEY)"))

    with engine.connect() as connection:
        assert table_privileges(connection, "future_table") == dict.fromkeys(
            DATA_PRIVILEGES, True
        )
        assert sequences_usable(connection)["future_table_id_seq"] is True


def test_downgrade_removes_access_and_upgrade_restores_it(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_APP_ROLE)
    command.downgrade(alembic_config, REMOVE_LEGACY_DEFAULT)

    with engine.connect() as connection:
        assert table_privileges(connection, "tasks") == dict.fromkeys(
            DATA_PRIVILEGES, False
        )

    # Default privileges are gone too: a new table gets no access.
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE after_downgrade (id integer)"))
        assert table_privileges(connection, "after_downgrade") == dict.fromkeys(
            DATA_PRIVILEGES, False
        )
        connection.execute(text("DROP TABLE after_downgrade"))

    command.upgrade(alembic_config, ADD_APP_ROLE)

    with engine.connect() as connection:
        assert table_privileges(connection, "tasks") == dict.fromkeys(
            DATA_PRIVILEGES, True
        )
