from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text


# Explicit revisions (not "head") keep the focused test valid after later migrations.
ADD_USERS = "505aa916db66"
ADD_TASK_OWNERSHIP = "32721ce95d01"


def schema_snapshot(engine: Engine) -> dict[str, dict]:
    """Tables with their columns, keys, constraints and indexes, comparable with ==."""
    inspector = inspect(engine)
    snapshot = {}

    for table in sorted(inspector.get_table_names()):
        snapshot[table] = {
            "columns": [
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns(table)
            ],
            "primary_key": inspector.get_pk_constraint(table),
            "foreign_keys": sorted(
                (fk["name"], tuple(fk["constrained_columns"]), fk["referred_table"])
                for fk in inspector.get_foreign_keys(table)
            ),
            "unique": sorted(
                (unique["name"], tuple(unique["column_names"]))
                for unique in inspector.get_unique_constraints(table)
            ),
            "checks": sorted(
                (check["name"], check["sqltext"])
                for check in inspector.get_check_constraints(table)
            ),
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), index["unique"])
                for index in inspector.get_indexes(table)
            ),
        }

    return snapshot


def test_full_downgrade_and_upgrade_round_trip(
    alembic_config: Config,
    engine: Engine,
) -> None:
    # Runs every downgrade in the chain, so a broken one fails here
    # instead of during a recovery.
    command.upgrade(alembic_config, "head")
    at_head = schema_snapshot(engine)

    command.downgrade(alembic_config, "base")

    # Only Alembic's own bookkeeping table remains.
    assert list(schema_snapshot(engine)) == ["alembic_version"]

    command.upgrade(alembic_config, "head")

    assert schema_snapshot(engine) == at_head


def test_task_ownership_downgrade_removes_owner_column(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_TASK_OWNERSHIP)

    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email, hashed_password) "
                "VALUES ('alice@example.com', 'hash') RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO tasks (title, completed, owner_id) "
                "VALUES ('משימה', false, :owner_id)"
            ),
            {"owner_id": user_id},
        )

    command.downgrade(alembic_config, ADD_USERS)

    inspector = inspect(engine)
    assert inspector.get_foreign_keys("tasks") == []
    assert "owner_id" not in {column["name"] for column in inspector.get_columns("tasks")}
    assert "ix_tasks_owner_id" not in {index["name"] for index in inspector.get_indexes("tasks")}

    with engine.connect() as connection:
        titles = connection.execute(text("SELECT title FROM tasks")).scalars().all()

    # The downgrade removes ownership, not the tasks themselves.
    assert titles == ["משימה"]
