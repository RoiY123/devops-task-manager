from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, inspect, text


# Explicit revisions (not "head") keep these tests valid after later migrations.
PRE = "32721ce95d01"
ADD_BUSINESSES = "652cc0a22e68"

SEED_USERS = [
    ("alice@example.com", "hash-alice"),
    ("bob@example.com", "hash-bob"),
    ("carol@example.com", "hash-carol"),
]

# Alice has several tasks, Bob one, Carol none.
SEED_TASKS = [
    ("alice@example.com", "Write the deployment runbook", False),
    ("alice@example.com", "לתקן את ה-API לפני 10:00", True),
    ("alice@example.com", "בדיקת גיבוי RDS", False),
    ("bob@example.com", "Rotate JWT secret", True),
]


def seed_pre_migration_data(connection: Connection) -> None:
    user_ids = {}

    for email, hashed_password in SEED_USERS:
        user_ids[email] = connection.execute(
            text(
                "INSERT INTO users (email, hashed_password) "
                "VALUES (:email, :hashed_password) RETURNING id"
            ),
            {"email": email, "hashed_password": hashed_password},
        ).scalar_one()

    for email, title, completed in SEED_TASKS:
        connection.execute(
            text(
                "INSERT INTO tasks (title, completed, owner_id) "
                "VALUES (:title, :completed, :owner_id)"
            ),
            {
                "title": title,
                "completed": completed,
                "owner_id": user_ids[email],
            },
        )


def snapshot(connection: Connection) -> dict[str, list[tuple]]:
    users = connection.execute(
        text("SELECT id, email, hashed_password FROM users ORDER BY id")
    ).all()

    tasks = connection.execute(
        text("SELECT id, title, completed, owner_id FROM tasks ORDER BY id")
    ).all()

    return {
        "users": [tuple(row) for row in users],
        "tasks": [tuple(row) for row in tasks],
    }


def legacy_business_id(connection: Connection) -> int:
    businesses = connection.execute(
        text("SELECT id, name, slug FROM businesses")
    ).all()

    assert len(businesses) == 1
    assert businesses[0].name == "Legacy"
    assert businesses[0].slug == "legacy"

    return businesses[0].id


def user_business_ids(connection: Connection) -> set[int | None]:
    return set(
        connection.execute(text("SELECT business_id FROM users")).scalars()
    )


def test_upgrade_preserves_existing_data(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, PRE)

    with engine.begin() as connection:
        seed_pre_migration_data(connection)
        before = snapshot(connection)

    assert len(before["users"]) == len(SEED_USERS)
    assert len(before["tasks"]) == len(SEED_TASKS)

    command.upgrade(alembic_config, ADD_BUSINESSES)

    with engine.begin() as connection:
        after = snapshot(connection)
        legacy_id = legacy_business_id(connection)

        # Same ids, field values (including Hebrew titles) and ownership.
        assert after == before
        assert "לתקן את ה-API לפני 10:00" in [
            title for _, title, _, _ in after["tasks"]
        ]

        assert user_business_ids(connection) == {legacy_id}

        # The previous app version inserts users without business_id;
        # the temporary default must place them in the legacy business.
        old_app_user = connection.execute(
            text(
                "INSERT INTO users (email, hashed_password) "
                "VALUES ('old-app@example.com', 'hash-old-app') "
                "RETURNING id, business_id"
            )
        ).one()

    assert old_app_user.business_id == legacy_id
    assert old_app_user.id > max(user_id for user_id, _, _ in before["users"])


def test_downgrade_then_upgrade_round_trip(
    alembic_config: Config,
    engine: Engine,
) -> None:
    command.upgrade(alembic_config, ADD_BUSINESSES)

    with engine.begin() as connection:
        legacy_id = legacy_business_id(connection)

        user_id = connection.execute(
            text(
                "INSERT INTO users (email, hashed_password, business_id) "
                "VALUES ('dana@example.com', 'hash-dana', :business_id) "
                "RETURNING id"
            ),
            {"business_id": legacy_id},
        ).scalar_one()

        connection.execute(
            text(
                "INSERT INTO tasks (title, completed, owner_id) "
                "VALUES ('הכנת דוח חודשי', false, :owner_id)"
            ),
            {"owner_id": user_id},
        )

        before = snapshot(connection)

    command.downgrade(alembic_config, PRE)

    inspector = inspect(engine)
    assert "businesses" not in inspector.get_table_names()
    assert "business_id" not in {
        column["name"] for column in inspector.get_columns("users")
    }

    with engine.begin() as connection:
        assert snapshot(connection) == before

    command.upgrade(alembic_config, ADD_BUSINESSES)

    with engine.begin() as connection:
        assert snapshot(connection) == before
        assert user_business_ids(connection) == {legacy_business_id(connection)}
