import os
from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.backend import cli, security
from app.backend.database import get_db
from app.backend.main import app
from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, User
from app.backend.security import hash_password


# Kept before any test swaps them, so the guard tests can check the real ones.
PRODUCTION_PASSWORD_HASH = security.password_hash
PRODUCTION_DUMMY_PASSWORD_HASH = security.DUMMY_PASSWORD_HASH

# Production's Argon2 settings cost about 45 ms per hash and per check,
# paid for every test user and login. Tests run the same code with minimal settings;
# test_security.py checks production's settings and hashing for real.
TEST_PASSWORD_HASH = PasswordHash(
    (Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1),)
)


@pytest.fixture(autouse=True, scope="session")
def cheap_password_hashing() -> Generator[None, None, None]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(security, "password_hash", TEST_PASSWORD_HASH)
        patch.setattr(
            security, "DUMMY_PASSWORD_HASH", TEST_PASSWORD_HASH.hash("not-a-real-password")
        )
        yield


@pytest.fixture
def production_password_hash() -> PasswordHash:
    return PRODUCTION_PASSWORD_HASH


@pytest.fixture
def production_dummy_password_hash() -> str:
    return PRODUCTION_DUMMY_PASSWORD_HASH


@pytest.fixture(autouse=True)
def no_real_terminal_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # termios exists on Linux (CI) but not on Windows. Disabling it by default
    # makes tests behave the same everywhere and keeps them from changing the
    # real terminal's settings; line-editing tests install their own fake.
    monkeypatch.setattr(cli, "termios", None)


TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/task_manager_test",
)

test_engine = create_engine(TEST_DATABASE_URL)

TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False,
)

@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    connection = test_engine.connect()
    transaction = connection.begin()

    # Commits and rollbacks inside application code act on a savepoint,
    # so they cannot end the outer transaction that isolates each test.
    session = TestingSessionLocal(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def test_business(db_session: Session) -> Business:
    business = Business(name="עסק בדיקות", slug="test-business")
    db_session.add(business)
    db_session.flush()

    return business


@pytest.fixture
def other_business(db_session: Session) -> Business:
    """A second business, for checking that nothing crosses businesses."""
    business = Business(name="עסק אחר", slug="other-business")
    db_session.add(business)
    db_session.flush()
    return business


@pytest.fixture
def user_factory(db_session: Session, test_business: Business):
    # Public registration is closed, so tests create users directly,
    # the same way the operator's onboarding code does.
    def create_user(
        email: str,
        password: str = "password123",
        role: str = ROLE_MEMBER,
        sees_all_tasks: bool | None = None,
        business: Business | None = None,
    ) -> User:
        # Same default as the application: admins see every task.
        if sees_all_tasks is None:
            sees_all_tasks = role == ROLE_ADMIN

        business = business or test_business
        user = User(
            email=email,
            hashed_password=hash_password(password),
            business=business,
            role=role,
            sees_all_tasks=sees_all_tasks,
        )
        db_session.add(user)
        db_session.flush()

        # Like onboarding and add-user: the first admin leads the business.
        if role == ROLE_ADMIN and business.leader_user_id is None:
            business.leader_user_id = user.id
            db_session.flush()

        return user

    return create_user


@pytest.fixture
def auth_headers_factory(client: TestClient, user_factory):
    def create_user(
        email: str,
        password: str = "password123",
        **options,
    ) -> dict[str, str]:
        user = user_factory(email, password, **options)

        login_response = client.post(
            f"/businesses/{user.business.slug}/login",
            json={"email": email, "password": password},
        )
        assert login_response.status_code == 200

        access_token = login_response.json()["access_token"]

        return {
            "Authorization": f"Bearer {access_token}",
        }

    return create_user


@pytest.fixture
def token_headers() -> Callable[[int, datetime | None], dict[str, str]]:
    """Login headers with a chosen issue time (iat), signed like the app's own tokens."""
    def make(user_id: int, issued_at: datetime | None) -> dict[str, str]:
        payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
        if issued_at is not None:
            payload["iat"] = issued_at
        encoded = jwt.encode(payload, security.JWT_SECRET_KEY, algorithm=security.JWT_ALGORITHM)
        return {"Authorization": f"Bearer {encoded}"}

    return make