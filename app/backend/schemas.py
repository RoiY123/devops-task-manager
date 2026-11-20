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


class GrantSummary(BaseModel):
    viewer_id: int
    viewer_email: str
    owner_id: int
    owner_email: str
    # "view" or "edit"
    permission: str