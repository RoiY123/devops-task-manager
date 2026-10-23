import os
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url


# Same default as tests/conftest.py.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/task_manager_test",
)

# Migration tests create and drop databases,
# so they must never reach a shared or production server such as RDS.
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres"}

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def disposable_db_url(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[str, None, None]:
    base_url = make_url(TEST_DATABASE_URL)

    if base_url.host not in ALLOWED_HOSTS:
        pytest.fail(
            f"Refusing to create migration test databases on host "
            f"{base_url.host!r}; allowed hosts: {sorted(ALLOWED_HOSTS)}"
        )

    database_name = f"migration_test_{uuid.uuid4().hex[:8]}"

    admin_engine = create_engine(
        base_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )

    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    database_url = base_url.set(database=database_name).render_as_string(
        hide_password=False
    )

    # alembic/env.py reads DATABASE_URL on every command.
    monkeypatch.setenv("DATABASE_URL", database_url)

    try:
        yield database_url
    finally:
        with admin_engine.connect() as connection:
            connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )

        admin_engine.dispose()


@pytest.fixture
def engine(disposable_db_url: str) -> Generator[Engine, None, None]:
    engine = create_engine(disposable_db_url)

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))
