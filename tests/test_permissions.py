import pytest
from sqlalchemy.orm import Session

from app.backend.accounts import grant_task_edit, set_task_editing
from app.backend.models import ROLE_ADMIN, Business, User
from app.backend.permissions import (
    ActionNotAllowed,
    check_grant,
    check_revoke,
    check_set_role,
    check_set_visibility,
    check_set_editing,
    check_transfer_leadership,
)


SLUG = "test-business"


@pytest.fixture
def people(
    db_session: Session,
    user_factory,
    other_business: Business,
) -> dict[str, User]:
    people = {
        # The first admin becomes the leader.
        "dana": user_factory("dana@example.com", role=ROLE_ADMIN),
        "eli": user_factory("eli@example.com", role=ROLE_ADMIN),
        "ori": user_factory("ori@example.com", role=ROLE_ADMIN),
        "gal": user_factory("gal@example.com", role=ROLE_ADMIN),
        "avi": user_factory("avi@example.com"),
        "noa": user_factory("noa@example.com"),
        "zoe": user_factory("zoe@example.com"),
        "boss": user_factory("boss@other.example", role=ROLE_ADMIN, business=other_business),
    }
    set_task_editing(db_session, business_slug=SLUG, email="ori@example.com", edits_all=True)
    grant_task_edit(
        db_session,
        business_slug=SLUG,
        viewer_email="gal@example.com",
        owner_email="avi@example.com",
    )
    return people


def assert_outcome(action, refusal: str | None) -> None:
    """None means the action is allowed; otherwise part of the expected reason."""
    if refusal is None:
        action()
    else:
        with pytest.raises(ActionNotAllowed, match=refusal):
            action()


MANAGE_CASES = [
    ("dana", "eli", None),
    ("dana", "avi", None),
    # No self-changes, the leader included.
    ("dana", "dana", "your own role or access"),
    ("eli", "avi", None),
    ("eli", "ori", "Admins can manage only members"),
    ("eli", "dana", "The leader's role and access"),
    ("eli", "eli", "your own role or access"),
    ("avi", "noa", "Only the leader and admins"),
    ("avi", "avi", "your own role or access"),
    ("dana", "boss", "User not found"),
]


@pytest.mark.parametrize("check", ["role", "visibility", "revoke"])
@pytest.mark.parametrize(("actor", "target", "refusal"), MANAGE_CASES)
def test_who_may_manage_whom(
    people: dict[str, User],
    check: str,
    actor: str,
    target: str,
    refusal: str | None,
) -> None:
    # Role changes, visibility and revoking need only the shared rules.
    acting, managed = people[actor], people[target]
    actions = {
        "role": lambda: check_set_role(acting, managed),
        "visibility": lambda: check_set_visibility(acting, managed),
        "revoke": lambda: check_revoke(acting, managed, people["zoe"]),
    }

    assert_outcome(actions[check], refusal)


@pytest.mark.parametrize(
    ("actor", "target", "edits_all", "refusal"),
    [
        # The leader decides admins' editing.
        ("dana", "eli", True, None),
        ("dana", "avi", True, None),
        # An admin who edits all may pass it on.
        ("ori", "avi", True, None),
        ("eli", "avi", True, "only if you edit all tasks"),
        # Reducing access is always allowed.
        ("eli", "avi", False, None),
    ],
)
def test_editing_all_is_never_given_above_your_own(
    people: dict[str, User],
    actor: str,
    target: str,
    edits_all: bool,
    refusal: str | None,
) -> None:
    assert_outcome(
        lambda: check_set_editing(people[actor], people[target], edits_all=edits_all),
        refusal,
    )


@pytest.mark.parametrize(
    ("actor", "owner", "permission", "refusal"),
    [
        # Admins see all tasks, so any view grant is within their own.
        ("eli", "avi", "view", None),
        # Even of the leader's tasks.
        ("eli", "dana", "view", None),
        ("eli", "avi", "edit", "only if you can change them"),
        # The admin's own tasks.
        ("eli", "eli", "edit", None),
        ("eli", "dana", "edit", "only if you can change them"),
        # Editing all includes the leader's tasks.
        ("ori", "dana", "edit", None),
        # An edit grant on Avi allows passing on Avi only.
        ("gal", "avi", "edit", None),
        ("gal", "zoe", "edit", "only if you can change them"),
        ("dana", "zoe", "edit", None),
        ("eli", "boss", "view", "User not found"),
    ],
)
def test_grants_are_never_given_above_your_own(
    db_session: Session,
    people: dict[str, User],
    actor: str,
    owner: str,
    permission: str,
    refusal: str | None,
) -> None:
    assert_outcome(
        lambda: check_grant(
            db_session, people[actor], people["noa"], people[owner], permission=permission
        ),
        refusal,
    )


@pytest.mark.parametrize(
    ("actor", "new_leader", "refusal"),
    [
        ("dana", "eli", None),
        ("eli", "ori", "Only the leader"),
        ("avi", "eli", "Only the leader"),
        ("dana", "boss", "User not found"),
    ],
)
def test_only_the_leader_transfers_leadership(
    people: dict[str, User],
    actor: str,
    new_leader: str,
    refusal: str | None,
) -> None:
    assert_outcome(
        lambda: check_transfer_leadership(people[actor], people[new_leader]), refusal
    )
