import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backend.accounts import (
    OperatorError,
    add_user,
    grant_task_edit,
    grant_task_view,
    list_task_grants,
    list_users,
    remove_user,
    reset_password,
    revoke_task_edit,
    revoke_task_view,
    set_role,
    set_task_editing,
    set_task_visibility,
    transfer_leadership,
)
from app.backend.models import ROLE_ADMIN, ROLE_MEMBER, Business, Task, User


SLUG = "test-business"
PASSWORD = "correct-horse-battery"


def login_status(client: TestClient, email: str, password: str) -> int:
    return client.post(
        "/businesses/test-business/login", json={"email": email, "password": password}
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
    user_factory,
) -> None:
    # A leader first: the first user of an empty business must be an admin.
    user_factory("dana@example.com", role=ROLE_ADMIN)

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


# What the left arrow key inserts at the CLI's prompts: ESC [ D.
ARROW_LEFT = chr(27) + "[D"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"business_slug": "no-such-business"}, "No business"),
        ({"email": "not-an-email"}, "is invalid"),
        ({"email": f"avi{ARROW_LEFT}@example.com"}, "Email contains control characters"),
        ({"role": "owner"}, "Role 'owner' is invalid"),
        ({"password": "short"}, "at least 12 characters"),
        ({"password": f"{PASSWORD}{ARROW_LEFT}"}, "Password contains control characters"),
    ],
)
def test_add_user_rejects_invalid_input_and_saves_nothing(
    db_session: Session,
    user_factory,
    overrides: dict[str, str],
    message: str,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
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


def test_add_user_allows_an_email_used_in_another_business(
    db_session: Session,
    user_factory,
    other_business: Business,
) -> None:
    user_factory("avi@example.com")
    user_factory("boss@other.example", role=ROLE_ADMIN, business=other_business)

    add_user(
        db_session,
        business_slug=other_business.slug,
        email="avi@example.com",
        role=ROLE_MEMBER,
        password=PASSWORD,
    )

    assert user_count(db_session, "avi@example.com") == 2


def test_add_user_rejects_an_email_taken_in_the_same_business(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")

    # Differs only in capitals, so it is the same email.
    with pytest.raises(
        OperatorError, match="already registered in business 'test-business'"
    ):
        add_user(
            db_session,
            business_slug=SLUG,
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
            Task(title="Avi 1", owner=avi, business_id=avi.business_id),
            Task(title="Avi 2", owner=avi, business_id=avi.business_id),
            Task(title="Noa 1", owner=noa, business_id=noa.business_id),
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


def test_leader_cannot_be_removed_while_other_users_remain(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    with pytest.raises(OperatorError, match="is the leader of 'test-business'"):
        remove_user(db_session, business_slug=SLUG, email="dana@example.com")

    assert user_count(db_session, "dana@example.com") == 1


def test_leader_can_be_removed_as_the_last_user(
    db_session: Session,
    user_factory,
    test_business: Business,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)

    remove_user(db_session, business_slug=SLUG, email="dana@example.com")

    # The business is now empty and leaderless, which deleting it requires.
    assert list_users(db_session, SLUG)[0].user_id is None
    assert test_business.leader_user_id is None


def test_admin_who_is_not_the_leader_can_be_removed(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com", role=ROLE_ADMIN)
    user_factory("noa@example.com")

    remove_user(db_session, business_slug=SLUG, email="avi@example.com")

    assert user_count(db_session, "avi@example.com") == 0


def test_set_role_promotes_and_demotes(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    avi = user_factory("avi@example.com")

    assert set_role(
        db_session, business_slug=SLUG, email="avi@example.com", role=ROLE_ADMIN
    ) == ROLE_MEMBER
    assert avi.role == ROLE_ADMIN

    set_role(db_session, business_slug=SLUG, email="avi@example.com", role=ROLE_MEMBER)
    assert avi.role == ROLE_MEMBER


def test_leader_cannot_be_demoted_or_restricted(
    db_session: Session,
    user_factory,
) -> None:
    dana = user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com", role=ROLE_ADMIN)

    with pytest.raises(OperatorError, match="transfer leadership first"):
        set_role(
            db_session, business_slug=SLUG, email="dana@example.com", role=ROLE_MEMBER
        )
    with pytest.raises(OperatorError, match="the leader always sees all tasks"):
        set_task_visibility(
            db_session, business_slug=SLUG, email="dana@example.com", sees_all=False
        )

    assert (dana.role, dana.sees_all_tasks) == (ROLE_ADMIN, True)


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


def test_new_admins_see_all_tasks_and_members_their_own(
    db_session: Session,
    test_business: Business,
) -> None:
    admin = add_user(
        db_session,
        business_slug=SLUG,
        email="dana@example.com",
        role=ROLE_ADMIN,
        password=PASSWORD,
    )
    member = add_user(
        db_session,
        business_slug=SLUG,
        email="avi@example.com",
        role=ROLE_MEMBER,
        password=PASSWORD,
    )

    assert (admin.sees_all_tasks, member.sees_all_tasks) == (True, False)


def test_role_change_applies_the_roles_defaults(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    avi = user_factory("avi@example.com")
    user_factory("noa@example.com")
    grant(db_session, "avi@example.com", "noa@example.com")

    set_role(db_session, business_slug=SLUG, email="avi@example.com", role=ROLE_ADMIN)
    assert (avi.sees_all_tasks, avi.edits_all_tasks) == (True, False)
    # Grants chosen for the previous role are dropped.
    assert grants(db_session) == []

    set_task_editing(db_session, business_slug=SLUG, email="avi@example.com", edits_all=True)
    set_role(db_session, business_slug=SLUG, email="avi@example.com", role=ROLE_MEMBER)
    assert (avi.sees_all_tasks, avi.edits_all_tasks) == (False, False)


def grants(db: Session) -> list[tuple[str, str, str]]:
    return [
        (row.viewer_email, row.owner_email, row.permission)
        for row in list_task_grants(db, SLUG)
    ]


def grant(db: Session, viewer: str, owner: str):
    return grant_task_view(
        db, business_slug=SLUG, viewer_email=viewer, owner_email=owner
    )


def test_grant_is_listed_and_repeating_it_changes_nothing(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")
    user_factory("noa@example.com")

    assert grant(db_session, "noa@example.com", "avi@example.com") is True
    assert grant(db_session, "noa@example.com", "avi@example.com") is False
    assert grants(db_session) == [("noa@example.com", "avi@example.com", "view")]


def test_revoke_removes_the_grant_and_reports_a_missing_one(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("avi@example.com")
    user_factory("noa@example.com")
    grant(db_session, "noa@example.com", "avi@example.com")
    pair = {
        "business_slug": SLUG,
        "viewer_email": "noa@example.com",
        "owner_email": "avi@example.com",
    }

    assert revoke_task_view(db_session, **pair) is True
    assert revoke_task_view(db_session, **pair) is False
    assert grants(db_session) == []


def test_grant_refuses_the_same_user_and_users_of_another_business(
    db_session: Session,
    user_factory,
    other_business: Business,
) -> None:
    user_factory("avi@example.com")
    user_factory("boss@other.example", business=other_business)

    with pytest.raises(OperatorError, match="always sees their own tasks"):
        grant(db_session, "avi@example.com", "Avi@Example.com")
    with pytest.raises(OperatorError, match="No user 'boss@other.example' in business"):
        grant(db_session, "boss@other.example", "avi@example.com")


def test_view_grant_is_refused_for_a_viewer_who_sees_all_tasks(
    db_session: Session,
    user_factory,
) -> None:
    user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("avi@example.com")

    with pytest.raises(OperatorError, match="already sees all tasks"):
        grant(db_session, "dana@example.com", "avi@example.com")


def test_removing_a_user_removes_their_grants_as_viewer_and_owner(
    db_session: Session,
    user_factory,
) -> None:
    for email in ["avi@example.com", "noa@example.com", "eli@example.com"]:
        user_factory(email)
    # Avi is the viewer in one grant and the owner in the other.
    grant(db_session, "avi@example.com", "noa@example.com")
    grant(db_session, "eli@example.com", "avi@example.com")

    remove_user(db_session, business_slug=SLUG, email="avi@example.com")

    assert grants(db_session) == []


def test_first_user_of_an_empty_business_must_be_an_admin_and_leads_it(
    db_session: Session,
    test_business: Business,
) -> None:
    with pytest.raises(OperatorError, match="becomes its leader; use --role admin"):
        add_user(
            db_session,
            business_slug=SLUG,
            email="avi@example.com",
            role=ROLE_MEMBER,
            password=PASSWORD,
        )

    dana = add_user(
        db_session,
        business_slug=SLUG,
        email="dana@example.com",
        role=ROLE_ADMIN,
        password=PASSWORD,
    )

    assert test_business.leader_user_id == dana.id


def test_transfer_makes_an_admin_the_leader_and_keeps_the_previous_one_admin(
    db_session: Session,
    user_factory,
    test_business: Business,
) -> None:
    dana = user_factory("dana@example.com", role=ROLE_ADMIN)
    avi = user_factory("avi@example.com", role=ROLE_ADMIN)
    # A stored setting the previous leader may carry; the leader edits all anyway.
    dana.edits_all_tasks = True
    db_session.flush()

    previous = transfer_leadership(db_session, business_slug=SLUG, email="avi@example.com")

    assert previous == "dana@example.com"
    assert test_business.leader_user_id == avi.id
    # Back to the admin defaults: sees all, edits own.
    assert (dana.role, dana.sees_all_tasks, dana.edits_all_tasks) == (ROLE_ADMIN, True, False)


@pytest.mark.parametrize(
    ("email", "message"),
    [
        ("noa@example.com", "is a member; promote them to admin first"),
        ("dana@example.com", "is already the leader"),
        ("boss@other.example", "No user 'boss@other.example' in business"),
    ],
)
def test_transfer_is_refused_for_a_member_the_leader_or_another_business(
    db_session: Session,
    user_factory,
    other_business: Business,
    test_business: Business,
    email: str,
    message: str,
) -> None:
    dana = user_factory("dana@example.com", role=ROLE_ADMIN)
    user_factory("noa@example.com")
    user_factory("boss@other.example", role=ROLE_ADMIN, business=other_business)

    with pytest.raises(OperatorError, match=message):
        transfer_leadership(db_session, business_slug=SLUG, email=email)

    assert test_business.leader_user_id == dana.id


def test_transfer_repairs_a_business_without_a_leader(
    db_session: Session,
    user_factory,
    test_business: Business,
) -> None:
    dana = user_factory("dana@example.com", role=ROLE_ADMIN)
    # What an image from before the leader migration could leave behind.
    test_business.leader_user_id = None
    db_session.flush()

    assert transfer_leadership(db_session, business_slug=SLUG, email="dana@example.com") is None
    assert test_business.leader_user_id == dana.id


def edit_grant(db: Session, viewer: str, owner: str) -> bool:
    return grant_task_edit(db, business_slug=SLUG, viewer_email=viewer, owner_email=owner)


def visibility(db: Session, email: str, sees_all: bool) -> None:
    set_task_visibility(db, business_slug=SLUG, email=email, sees_all=sees_all)


def editing(db: Session, email: str, edits_all: bool) -> None:
    set_task_editing(db, business_slug=SLUG, email=email, edits_all=edits_all)


@pytest.fixture
def team(user_factory) -> dict[str, User]:
    """Dana leads; Eli is an admin; Avi, Noa and Zoe are members."""
    return {
        "dana": user_factory("dana@example.com", role=ROLE_ADMIN),
        "eli": user_factory("eli@example.com", role=ROLE_ADMIN),
        "avi": user_factory("avi@example.com"),
        "noa": user_factory("noa@example.com"),
        "zoe": user_factory("zoe@example.com"),
    }


def test_admins_and_the_leader_cannot_be_limited_to_their_own_tasks(
    db_session: Session,
    team: dict[str, User],
) -> None:
    with pytest.raises(OperatorError, match="admins always see all tasks"):
        visibility(db_session, "eli@example.com", False)
    with pytest.raises(OperatorError, match="the leader always sees all tasks"):
        visibility(db_session, "dana@example.com", False)
    with pytest.raises(OperatorError, match="the leader always edits all tasks"):
        editing(db_session, "dana@example.com", False)


def test_own_visibility_drops_all_grants_and_editing(
    db_session: Session,
    team: dict[str, User],
) -> None:
    noa = team["noa"]
    visibility(db_session, "noa@example.com", True)
    editing(db_session, "noa@example.com", True)

    visibility(db_session, "noa@example.com", False)
    assert (noa.sees_all_tasks, noa.edits_all_tasks) == (False, False)

    grant(db_session, "noa@example.com", "avi@example.com")
    edit_grant(db_session, "noa@example.com", "avi@example.com")
    visibility(db_session, "noa@example.com", False)
    assert grants(db_session) == []


def test_all_visibility_keeps_edit_grants_and_drops_view_grants(
    db_session: Session,
    team: dict[str, User],
) -> None:
    grant(db_session, "noa@example.com", "avi@example.com")
    grant(db_session, "noa@example.com", "zoe@example.com")
    edit_grant(db_session, "noa@example.com", "zoe@example.com")

    visibility(db_session, "noa@example.com", True)

    assert grants(db_session) == [("noa@example.com", "zoe@example.com", "edit")]


def test_editing_all_requires_seeing_all_and_replaces_grants(
    db_session: Session,
    team: dict[str, User],
) -> None:
    with pytest.raises(OperatorError, match="set visibility to all first"):
        editing(db_session, "noa@example.com", True)

    visibility(db_session, "noa@example.com", True)
    edit_grant(db_session, "noa@example.com", "avi@example.com")
    editing(db_session, "noa@example.com", True)

    assert team["noa"].edits_all_tasks is True
    assert grants(db_session) == []


@pytest.mark.parametrize(("sees_all", "remaining"), [(False, "view"), (True, None)])
def test_own_editing_downgrades_edit_grants_or_drops_them_when_seeing_all(
    db_session: Session,
    team: dict[str, User],
    sees_all: bool,
    remaining: str | None,
) -> None:
    if sees_all:
        visibility(db_session, "noa@example.com", True)
    else:
        grant(db_session, "noa@example.com", "avi@example.com")
    edit_grant(db_session, "noa@example.com", "avi@example.com")

    editing(db_session, "noa@example.com", False)

    expected = [("noa@example.com", "avi@example.com", remaining)] if remaining else []
    assert grants(db_session) == expected


def test_edit_grant_needs_view_and_upgrades_a_view_grant(
    db_session: Session,
    team: dict[str, User],
) -> None:
    with pytest.raises(OperatorError, match="cannot see the tasks of avi@example.com"):
        edit_grant(db_session, "noa@example.com", "avi@example.com")

    grant(db_session, "noa@example.com", "avi@example.com")
    assert edit_grant(db_session, "noa@example.com", "avi@example.com") is True
    assert edit_grant(db_session, "noa@example.com", "avi@example.com") is False
    assert grants(db_session) == [("noa@example.com", "avi@example.com", "edit")]


def test_edit_grant_for_a_user_who_sees_all_and_refusals(
    db_session: Session,
    team: dict[str, User],
) -> None:
    # Admins see all, so an edit grant needs no view grant first.
    assert edit_grant(db_session, "eli@example.com", "avi@example.com") is True
    assert grants(db_session) == [("eli@example.com", "avi@example.com", "edit")]

    with pytest.raises(OperatorError, match="the leader always edits all tasks"):
        edit_grant(db_session, "dana@example.com", "avi@example.com")

    editing(db_session, "eli@example.com", True)
    with pytest.raises(OperatorError, match="already edits all tasks"):
        edit_grant(db_session, "eli@example.com", "noa@example.com")


def test_revoking_an_edit_grant_keeps_the_view_unless_the_user_sees_all(
    db_session: Session,
    team: dict[str, User],
) -> None:
    grant(db_session, "noa@example.com", "avi@example.com")
    edit_grant(db_session, "noa@example.com", "avi@example.com")
    edit_grant(db_session, "eli@example.com", "avi@example.com")
    pair = {"business_slug": SLUG, "owner_email": "avi@example.com"}

    assert revoke_task_edit(db_session, viewer_email="noa@example.com", **pair) is True
    assert revoke_task_edit(db_session, viewer_email="eli@example.com", **pair) is True
    assert revoke_task_edit(db_session, viewer_email="noa@example.com", **pair) is False
    assert grants(db_session) == [("noa@example.com", "avi@example.com", "view")]


def test_list_users_shows_custom_levels_for_users_with_grants(
    db_session: Session,
    team: dict[str, User],
) -> None:
    grant(db_session, "noa@example.com", "avi@example.com")
    edit_grant(db_session, "noa@example.com", "avi@example.com")
    grant(db_session, "zoe@example.com", "avi@example.com")

    levels = {
        row.email: (row.view_level, row.edit_level) for row in list_users(db_session, SLUG)
    }

    assert levels == {
        "dana@example.com": ("all", "all"),
        "eli@example.com": ("all", "own"),
        "avi@example.com": ("own", "own"),
        "noa@example.com": ("custom", "custom"),
        "zoe@example.com": ("custom", "own"),
    }
