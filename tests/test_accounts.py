import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.accounts import (
    OperatorError,
    add_user,
    list_users,
    remove_user,
    reset_password,
    set_role,
)
from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, Task, User


SLUG = "test-business"
PASSWORD = "correct-horse-battery"


def login_status(client: TestClient, email: str, password: str) -> int:
    return client.post(
        "/login", json={"email": email, "password": password}
    ).status_code


def user_count(db: Session, email: str) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.email == email)
    )


@pytest.fixture
def other_business(db_session: Session) -> Business:
    business = Business(name="עסק אחר", slug="other-business")
    db_session.add(business)
    db_session.flush()
    return business


def test_add_user_creates_member_who_can_log_in(
    client: TestClient,
    db_session: Session,
    test_business: Business,
) -> None:
    user = add_user(
        db_session,
        business_slug=SLUG,
        email="avi@example.com",
        role=ROLE_MEMBER,
        password=PASSWORD,
    )

    assert user.business_id == test_business.id
    assert user.role == ROLE_MEMBER
    assert login_status(client, "avi@example.com", PASSWORD) == 200


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"business_slug": "no-such-business"}, "No business"),
        ({"email": "not-an-email"}, "is invalid"),
        ({"role": "owner"}, "Role 'owner' is invalid"),
        ({"password": "short"}, "at least 12 characters"),
    ],
)
def test_add_user_rejects_invalid_input_and_saves_nothing(
    db_session: Session,
    test_business: Business,
    overrides: dict[str, str],
    message: str,
) -> None:
    data = {
        "business_slug": SLUG,
        "email": "avi@example.com",
        "role": ROLE_MEMBER,
        "password": PASSWORD,
        **overrides,
    }

    with pytest.raises(OperatorError, match=message):
        add_user(db_session, **data)

    assert user_count(db_session, data["email"]) == 0


def test_add_user_rejects_email_used_in_any_business(
    db_session: Session,
    user_factory,
    other_business: Business,
) -> None:
    user_factory("avi@example.com")

    # Different business and capitalisation: still the same email globally.
    with pytest.raises(OperatorError, match="already registered"):
        add_user(
            db_session,
            business_slug=other_business.slug,
            email="Avi@Example.com",
            role=ROLE_MEMBER,
            password=PASSWORD,
        )


def test_reset_password_replaces_the_old_one(
    client: TestClient,
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com", password="old-password-123")

    reset_password(
        db_session,
        business_slug=SLUG,
        email="Avi@Example.com",
        password=PASSWORD,
    )

    assert login_status(client, "avi@example.com", "old-password-123") == 401
    assert login_status(client, "avi@example.com", PASSWORD) == 200


def test_actions_only_find_users_in_the_named_business(
    db_session: Session,
    user_factory,
    other_business: Business,
) -> None:
    user_factory("avi@example.com")

    # Guards against changing a user of the wrong business by mistake.
    with pytest.raises(OperatorError, match="No user 'avi@example.com' in business"):
        reset_password(
            db_session,
            business_slug=other_business.slug,
            email="avi@example.com",
            password=PASSWORD,
        )


def test_remove_user_deletes_the_user_and_only_their_tasks(
    db_session: Session,
    user_factory,
) -> None:
    avi = user_factory("avi@example.com")
    noa = user_factory("noa@example.com")
    db_session.add_all(
        [
            Task(title="Avi 1", owner=avi),
            Task(title="Avi 2", owner=avi),
            Task(title="Noa 1", owner=noa),
        ]
    )
    db_session.flush()
    avi_id = avi.id

    deleted_tasks = remove_user(
        db_session, business_slug=SLUG, email="avi@example.com"
    )

    assert deleted_tasks == 2
    assert db_session.get(User, avi_id) is None
    assert db_session.scalar(
        select(func.count()).select_from(Task).where(Task.owner_id == avi_id)
    ) == 0
    assert [task.title for task in noa.tasks] == ["Noa 1"]


def test_removed_users_existing_token_is_rejected(
    client: TestClient,
    db_session: Session,
    auth_headers_factory,
) -> None:
    headers = auth_headers_factory("avi@example.com")
    assert client.get("/tasks", headers=headers).status_code == 200

    remove_user(db_session, business_slug=SLUG, email="avi@example.com")

    assert client.get("/tasks", headers=headers).status_code == 401


def test_only_admin_cannot_be_removed_while_other_users_remain(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    with pytest.raises(OperatorError, match="only admin"):
        remove_user(db_session, business_slug=SLUG, email="dana@example.com")

    assert user_count(db_session, "dana@example.com") == 1


def test_only_admin_can_be_removed_when_no_other_users_remain(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)

    remove_user(db_session, business_slug=SLUG, email="dana@example.com")

    # The business is now empty, which is what deleting it will require.
    assert list_users(db_session, SLUG)[0].user_id is None


def test_admin_can_be_removed_when_another_admin_remains(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com", role=ROLE_ADMIN)
    user_factory("noa@example.com")

    remove_user(db_session, business_slug=SLUG, email="dana@example.com")

    assert user_count(db_session, "dana@example.com") == 0


def test_set_role_promotes_and_demotes(
    db_session: Session,
    user_factory,
) -> None:
    dana = user_factory("dana@example.com", role=ROLE_ADMIN)
    avi = user_factory("avi@example.com")

    assert set_role(
        db_session, business_slug=SLUG, email="avi@example.com", role=ROLE_ADMIN
    ) == ROLE_MEMBER
    assert avi.role == ROLE_ADMIN

    # Dana is no longer the only admin, so she can be demoted.
    set_role(
        db_session, business_slug=SLUG, email="dana@example.com", role=ROLE_MEMBER
    )
    assert dana.role == ROLE_MEMBER


def test_only_admin_cannot_be_demoted(
    db_session: Session,
    user_factory,
) -> None:
    dana = user_factory("dana@example.com", role=ROLE_ADMIN)

    # Even as the only user: a business with users needs an admin.
    with pytest.raises(OperatorError, match="only admin"):
        set_role(
            db_session, business_slug=SLUG, email="dana@example.com", role=ROLE_MEMBER
        )

    assert dana.role == ROLE_ADMIN


def test_list_users_shows_empty_businesses_and_filters_by_slug(
    db_session: Session,
    user_factory,
    other_business: Business,
) -> None:
    user_factory("avi@example.com")

    everything = list_users(db_session)
    test_rows = [row for row in everything if row.business_slug == SLUG]
    other_rows = [row for row in everything if row.business_slug == "other-business"]

    assert [(row.email, row.role) for row in test_rows] == [
        ("avi@example.com", ROLE_MEMBER)
    ]
    assert [row.user_id for row in other_rows] == [None]

    only_test = list_users(db_session, SLUG)
    assert {row.business_slug for row in only_test} == {SLUG}

    with pytest.raises(OperatorError, match="No business"):
        list_users(db_session, "no-such-business")
