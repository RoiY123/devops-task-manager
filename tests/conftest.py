import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.backend.database import get_db
from app.backend.main import app
from app.backend.models import ROLE_MEMBER, Business, User
from app.backend.security import hash_password


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

    session = TestingSessionLocal(bind=connection)

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
def user_factory(db_session: Session, test_business: Business):
    # Public registration is closed, so tests create users directly,
    # the same way the operator's onboarding code does.
    def create_user(
        email: str,
        password: str = "password123",
        role: str = ROLE_MEMBER,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            business=test_business,
            role=role,
        )
        db_session.add(user)
        db_session.flush()

        return user

    return create_user


@pytest.fixture
def auth_headers_factory(client: TestClient, user_factory):
    def create_user(
        email: str,
        password: str = "password123",
    ) -> dict[str, str]:
        user_factory(email, password)

        login_response = client.post(
            "/login",
            json={"email": email, "password": password},
        )
        assert login_response.status_code == 200

        access_token = login_response.json()["access_token"]

        return {
            "Authorization": f"Bearer {access_token}",
        }

    return create_user