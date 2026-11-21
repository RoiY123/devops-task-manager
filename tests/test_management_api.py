import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.accounts import grant_task_edit, grant_task_view
from app.backend.models import ROLE_ADMIN, Business, User


SLUG = "test-business"


@pytest.fixture
def headers(
    db_session: Session,
    auth_headers_factory,
    other_business: Business,
) -> dict[str, dict[str, str]]:
    """Dana leads; Eli is an admin; Avi and Noa are members; Boss is in another business.

    Noa may see and change Avi's tasks (custom); Boss has a grant in his own business.
    """
    people = {
        "dana": auth_headers_factory("dana@example.com", role=ROLE_ADMIN),
        "eli": auth_headers_factory("eli@example.com", role=ROLE_ADMIN),
        "avi": auth_headers_factory("avi@example.com"),
        "noa": auth_headers_factory("noa@example.com"),
        "boss": auth_headers_factory(
            "boss@other.example", role=ROLE_ADMIN, business=other_business
        ),
        "sam": auth_headers_factory("sam@other.example", business=other_business),
    }
    pair = {"viewer_email": "noa@example.com", "owner_email": "avi@example.com"}
    grant_task_view(db_session, business_slug=SLUG, **pair)
    grant_task_edit(db_session, business_slug=SLUG, **pair)
    grant_task_view(
        db_session,
        business_slug="other-business",
        viewer_email="sam@other.example",
        owner_email="boss@other.example",
    )
    return people


@pytest.mark.parametrize(
    ("person", "expected"),
    [
        ("dana", {"role": "leader", "sees": "all", "edits": "all", "can_manage": True}),
        ("eli", {"role": "admin", "sees": "all", "edits": "own", "can_manage": True}),
        ("avi", {"role": "member", "sees": "own", "edits": "own", "can_manage": False}),
        ("noa", {"role": "member", "sees": "custom", "edits": "custom", "can_manage": False}),
    ],
)
def test_me_describes_the_caller_for_every_role(
    client: TestClient,
    headers: dict[str, dict[str, str]],
    person: str,
    expected: dict,
) -> None:
    response = client.get("/me", headers=headers[person])

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == f"{person}@example.com"
    assert body["business_slug"] == SLUG
    assert {key: body[key] for key in expected} == expected


@pytest.mark.parametrize("person", ["dana", "eli"])
def test_leader_and_admins_list_their_business_users_with_levels(
    client: TestClient,
    headers: dict[str, dict[str, str]],
    person: str,
) -> None:
    response = client.get("/business/users", headers=headers[person])

    assert response.status_code == 200
    levels = {user["email"]: (user["role"], user["sees"], user["edits"]) for user in response.json()}
    # Another business's users never appear.
    assert levels == {
        "dana@example.com": ("leader", "all", "all"),
        "eli@example.com": ("admin", "all", "own"),
        "avi@example.com": ("member", "own", "own"),
        "noa@example.com": ("member", "custom", "custom"),
    }


def test_grants_list_has_ids_and_stays_in_the_business(
    client: TestClient,
    headers: dict[str, dict[str, str]],
) -> None:
    users = {
        user["email"]: user["id"]
        for user in client.get("/business/users", headers=headers["eli"]).json()
    }

    response = client.get("/business/grants", headers=headers["eli"])

    assert response.status_code == 200
    # Only this business's grant; Sam's grant in the other business never appears.
    assert response.json() == [
        {
            "viewer_id": users["noa@example.com"],
            "viewer_email": "noa@example.com",
            "owner_id": users["avi@example.com"],
            "owner_email": "avi@example.com",
            "permission": "edit",
        }
    ]


@pytest.mark.parametrize("path", ["/business/users", "/business/grants"])
def test_members_cannot_read_management_data(
    client: TestClient,
    headers: dict[str, dict[str, str]],
    path: str,
) -> None:
    response = client.get(path, headers=headers["noa"])

    assert response.status_code == 403
    assert response.json()["detail"] == "Only the leader and admins can manage users"


@pytest.mark.parametrize("path", ["/me", "/business/users", "/business/grants"])
def test_management_endpoints_need_a_login(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


def user_ids(db: Session) -> dict[str, int]:
    """Ids by the part of the email before @, for filling in paths like {avi}."""
    return {user.email.split("@")[0]: user.id for user in db.scalars(select(User))}


def business_state(client: TestClient, headers: dict[str, str]) -> tuple:
    return (
        client.get("/business/users", headers=headers).json(),
        client.get("/business/grants", headers=headers).json(),
    )


@pytest.mark.parametrize(
    ("actor", "method", "path", "body", "expected"),
    [
        (
            "dana", "PUT", "/business/users/{avi}/role", {"role": "admin"},
            {"role": "admin", "sees": "all", "edits": "own"},
        ),
        ("eli", "PUT", "/business/users/{avi}/task-visibility", {"level": "all"}, {"sees": "all"}),
        ("dana", "PUT", "/business/users/{eli}/task-editing", {"level": "all"}, {"edits": "all"}),
        ("eli", "POST", "/business/users/{avi}/view-grants/{noa}", None, {"sees": "custom"}),
        ("dana", "POST", "/business/users/{eli}/edit-grants/{avi}", None, {"edits": "custom"}),
        # Revoking editing keeps the view; revoking the view removes both.
        (
            "eli", "DELETE", "/business/users/{noa}/edit-grants/{avi}", None,
            {"sees": "custom", "edits": "own"},
        ),
        (
            "eli", "DELETE", "/business/users/{noa}/view-grants/{avi}", None,
            {"sees": "own", "edits": "own"},
        ),
    ],
)
def test_change_endpoints_apply_the_change_and_return_it(
    client: TestClient,
    db_session: Session,
    headers: dict[str, dict[str, str]],
    actor: str,
    method: str,
    path: str,
    body: dict | None,
    expected: dict,
) -> None:
    response = client.request(
        method, path.format(**user_ids(db_session)), headers=headers[actor], json=body
    )

    assert response.status_code == 200
    returned = response.json()
    assert {key: returned[key] for key in expected} == expected
    # What was returned is what was saved.
    listed = client.get("/business/users", headers=headers["dana"]).json()
    assert returned in listed


@pytest.mark.parametrize(
    ("actor", "method", "path", "body", "status", "reason"),
    [
        ("dana", "PUT", "/business/users/{boss}/role", {"role": "admin"}, 404, "User not found"),
        ("eli", "POST", "/business/users/{noa}/view-grants/{boss}", None, 404, "User not found"),
        (
            "noa", "PUT", "/business/users/{avi}/task-visibility", {"level": "all"},
            403, "Only the leader and admins",
        ),
        ("eli", "PUT", "/business/users/{dana}/role", {"role": "member"}, 403, "The leader's role"),
        (
            "eli", "PUT", "/business/users/{ori}/role", {"role": "member"},
            403, "Admins can manage only members",
        ),
        ("eli", "PUT", "/business/users/{eli}/task-editing", {"level": "all"}, 403, "your own"),
        (
            "eli", "PUT", "/business/users/{avi}/task-editing", {"level": "all"},
            403, "only if you edit all",
        ),
        (
            "eli", "POST", "/business/users/{noa}/edit-grants/{dana}", None,
            403, "only if you can change them",
        ),
        (
            "dana", "PUT", "/business/users/{avi}/task-editing", {"level": "all"},
            400, "set visibility to all first",
        ),
        (
            "dana", "PUT", "/business/users/{eli}/task-visibility", {"level": "own"},
            400, "admins always see all",
        ),
        ("dana", "PUT", "/business/users/{avi}/task-visibility", {"level": "some"}, 422, None),
    ],
)
def test_refused_changes_report_why_and_change_nothing(
    client: TestClient,
    db_session: Session,
    headers: dict[str, dict[str, str]],
    auth_headers_factory,
    actor: str,
    method: str,
    path: str,
    body: dict | None,
    status: int,
    reason: str | None,
) -> None:
    # A second admin, for an admin acting on an admin.
    auth_headers_factory("ori@example.com", role=ROLE_ADMIN)
    before = business_state(client, headers["dana"])

    response = client.request(
        method, path.format(**user_ids(db_session)), headers=headers[actor], json=body
    )

    assert response.status_code == status
    if reason is not None:
        assert reason in response.json()["detail"]
    assert business_state(client, headers["dana"]) == before


def test_leader_transfers_leadership_and_both_rows_are_returned(
    client: TestClient,
    db_session: Session,
    headers: dict[str, dict[str, str]],
) -> None:
    response = client.post(
        "/business/leadership",
        headers=headers["dana"],
        json={"user_id": user_ids(db_session)["eli"]},
    )

    assert response.status_code == 200
    assert [(user["email"], user["role"], user["sees"], user["edits"]) for user in response.json()] == [
        ("eli@example.com", "leader", "all", "all"),
        ("dana@example.com", "admin", "all", "own"),
    ]


@pytest.mark.parametrize(
    ("actor", "to", "status", "reason"),
    [
        ("eli", "noa", 403, "Only the leader"),
        ("dana", "avi", 400, "promote them to admin first"),
        ("dana", "boss", 404, "User not found"),
    ],
)
def test_refused_transfers(
    client: TestClient,
    db_session: Session,
    headers: dict[str, dict[str, str]],
    actor: str,
    to: str,
    status: int,
    reason: str,
) -> None:
    before = business_state(client, headers["dana"])

    response = client.post(
        "/business/leadership",
        headers=headers[actor],
        json={"user_id": user_ids(db_session)[to]},
    )

    assert response.status_code == status
    assert reason in response.json()["detail"]
    assert business_state(client, headers["dana"]) == before
