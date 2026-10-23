from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, ForeignKey, UniqueConstraint, func
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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

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

    # Do not delete or detach users when deleting a business.
    # Let the database reject the deletion if users remain.
    users: Mapped[list["User"]] = relationship(
        back_populates="business",
        passive_deletes="all",
    )


class Task(Base):
    __tablename__ = "tasks"

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

    owner: Mapped["User"] = relationship(
        back_populates="tasks",
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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        nullable=False,
        index=True,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # The database also has a temporary default (the legacy business)
    # so the previous app version can still insert users.
    # Application code must set business_id explicitly.
    # The default is removed when public registration is closed.
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
    )

    # Missing roles default to the lowest permission, which keeps older
    # application versions safe to run against this schema.
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=ROLE_MEMBER,
    )

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )