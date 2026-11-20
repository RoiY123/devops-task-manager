import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.backend.accounts import grant_task_edit, grant_task_view
from app.backend.models import ROLE_ADMIN, Business


SLUG = "test-business"


@pytest.fixture
def other_business(db_session: Session) -> Business:
    business = Business(name="עסק אחר", slug="other-business")
    db_session.add(business)
    db_session.flush()
    return business


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
