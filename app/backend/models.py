from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, PrimaryKeyConstraint, String, ForeignKey, UniqueConstraint, false, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = "businesses"

    __table_args__ = (
        UniqueConstraint("slug", name="uq_businesses_slug"),
        # ASCII-only slugs keep business login URLs readable and easy to share.
        CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_businesses_slug_format",
        ),
        # The leader is one of the business's own users, and cannot be deleted
        # while recorded here. use_alter: users and businesses point at each other,
        # so this key is created after both tables.
        ForeignKeyConstraint(
            ["id", "leader_user_id"],
            ["users.business_id", "users.id"],
            name="fk_businesses_id_leader_user_id_users",
            use_alter=True,
        ),
    )

    # Explicit: id is also part of the leader foreign key,
    # which would otherwise stop SQLAlchemy from letting the database generate it.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Display name; may be Hebrew.
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(63),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Empty only while the business has no users.
    leader_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Do not delete or detach users when deleting a business.
    # Let the database reject the deletion if users remain.
    users: Mapped[list["User"]] = relationship(
        back_populates="business",
        passive_deletes="all",
        foreign_keys="User.business_id",
    )


class Task(Base):
    __tablename__ = "tasks"

    __table_args__ = (
        # A task always belongs to its owner's business.
        ForeignKeyConstraint(
            ["business_id", "owner_id"],
            ["users.business_id", "users.id"],
            name="fk_tasks_business_id_owner_id_users",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    completed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    business_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    owner: Mapped["User"] = relationship(
        back_populates="tasks",
        foreign_keys=[owner_id],
    )


ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'member')",
            name="ck_users_role",
        ),
        # Target of fk_tasks_business_id_owner_id_users.
        UniqueConstraint("business_id", "id", name="uq_users_business_id_id"),
        # Admins always see every task in their business.
        CheckConstraint(
            "role <> 'admin' OR sees_all_tasks",
            name="ck_users_admin_sees_all",
        ),
        # Edit access never exceeds view access.
        CheckConstraint(
            "NOT edits_all_tasks OR sees_all_tasks",
            name="ck_users_edits_all_needs_sees_all",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # No default: every code path that creates a user must choose its business,
    # so a missing business fails instead of silently picking one.
    business_id: Mapped[int] = mapped_column(
        ForeignKey(
            "businesses.id",
            name="fk_users_business_id_businesses",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    business: Mapped["Business"] = relationship(
        back_populates="users",
        foreign_keys=[business_id],
    )

    # Missing roles default to the lowest permission, which keeps older
    # application versions safe to run against this schema.
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=ROLE_MEMBER,
    )

    # Whether the user sees every task in the business, not only their own.
    sees_all_tasks: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )

    # Whether the user may change every task in the business; requires sees_all_tasks.
    edits_all_tasks: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )

    # Login tokens issued before this moment are refused; NULL means no cut-off.
    tokens_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Set while the password is temporary: chosen by someone else, so the user must
    # change it, and useless after this moment. NULL means a normal password.
    temporary_password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Task.owner_id",
    )

    @property
    def is_leader(self) -> bool:
        return self.business.leader_user_id == self.id

    @property
    def must_change_password(self) -> bool:
        return self.temporary_password_expires_at is not None


PERMISSION_VIEW = "view"
# An edit grant also lets the viewer see the owner's tasks.
PERMISSION_EDIT = "edit"


class TaskGrant(Base):
    """The viewer may see, or see and change, every task of the owner; both are in one business."""

    __tablename__ = "task_grants"

    __table_args__ = (
        # One grant per pair; a later 'edit' permission changes the row, not adds one.
        PrimaryKeyConstraint("viewer_id", "owner_id", name="pk_task_grants"),
        # Both users must belong to the grant's business, so grants never cross businesses.
        # Removing either user removes the grant with them.
        ForeignKeyConstraint(
            ["business_id", "viewer_id"],
            ["users.business_id", "users.id"],
            name="fk_task_grants_business_id_viewer_id_users",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["business_id", "owner_id"],
            ["users.business_id", "users.id"],
            name="fk_task_grants_business_id_owner_id_users",
            ondelete="CASCADE",
        ),
        CheckConstraint("viewer_id <> owner_id", name="ck_task_grants_not_self"),
        CheckConstraint("permission IN ('view', 'edit')", name="ck_task_grants_permission"),
    )

    viewer_id: Mapped[int] = mapped_column(Integer)
    # Indexed so removing an owner finds their grants quickly.
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False)
    permission: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=PERMISSION_VIEW
    )


ACTOR_USER = "user"
ACTOR_OPERATOR = "operator"


class AuditEvent(Base):
    """One successful change, recorded with the change itself.

    No foreign keys and copied emails and slug: the history outlives removed
    users and deleted businesses. The application role cannot update or
    delete rows.
    """

    __tablename__ = "audit_events"

    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_audit_events"),
        CheckConstraint(
            "actor_kind IN ('user', 'operator')", name="ck_audit_events_actor_kind"
        ),
        # A user event names its user; an operator event names no one.
        # Unknown kinds are left to ck_audit_events_actor_kind,
        # so each refusal names the rule that was broken.
        CheckConstraint(
            "(actor_kind <> 'user' OR (actor_user_id IS NOT NULL AND actor_email IS NOT NULL))"
            " AND (actor_kind <> 'operator' OR (actor_user_id IS NULL AND actor_email IS NULL))",
            name="ck_audit_events_actor",
        ),
        Index("ix_audit_events_business_id_occurred_at", "business_id", "occurred_at"),
    )

    # BigInteger: a log that grows for years never runs out of numbers.
    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    business_id: Mapped[int] = mapped_column(Integer, nullable=False)
    business_slug: Mapped[str] = mapped_column(String(63), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


# The same email may belong to different businesses;
# within one business, emails must differ by more than capitals.
Index(
    "uq_users_business_id_lower_email",
    User.business_id,
    func.lower(User.email),
    unique=True,
)
