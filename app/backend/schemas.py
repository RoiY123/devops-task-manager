from typing import Literal

from pydantic import BaseModel


class Task(BaseModel):
    id: int
    title: str
    completed: bool
    owner_id: int


class TaskCreate(BaseModel):
    title: str


class TaskUpdate(BaseModel):
    title: str | None = None
    completed: bool | None = None


class UserLogin(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    # The password is temporary: until it is changed, little else works.
    must_change_password: bool


class UserSummary(BaseModel):
    id: int
    email: str
    # "leader", "admin" or "member"
    role: str
    # "own", "all" or "custom"; the page's three choices
    sees: str
    edits: str


class Me(UserSummary):
    business_slug: str
    # Whether the management page applies to this user (leader or admin).
    can_manage: bool
    must_change_password: bool


class GrantSummary(BaseModel):
    viewer_id: int
    viewer_email: str
    owner_id: int
    owner_email: str
    # "view" or "edit"
    permission: str


class RoleChange(BaseModel):
    role: Literal["admin", "member"]


class LevelChange(BaseModel):
    level: Literal["own", "all"]


class LeadershipTransfer(BaseModel):
    user_id: int


class NewUser(BaseModel):
    email: str
    role: Literal["admin", "member"]


class AddedUser(BaseModel):
    user: UserSummary
    # Shown once; only its hash is stored.
    temporary_password: str


class TemporaryPassword(BaseModel):
    # Shown once; only its hash is stored.
    temporary_password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str