from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.accounts import (
    OperatorError,
    check_password,
    clean_email,
)
from app.backend.businesses import clean_business_name, clean_slug
from app.backend.models import ROLE_ADMIN, Business, User
from app.backend.security import hash_password


@dataclass(frozen=True)
class NewBusiness:
    name: str
    slug: str
    admin_email: str


@dataclass(frozen=True)
class OnboardedBusiness:
    business_id: int
    slug: str
    admin_user_id: int
    admin_email: str


def validate_new_business(
    db: Session,
    *,
    name: str,
    slug: str,
    admin_email: str,
) -> NewBusiness:
    """Check everything except the password, so the CLI can fail before prompting."""
    name = clean_business_name(name)
    slug = clean_slug(slug)
    admin_email = clean_email(admin_email)

    if db.scalar(select(Business.id).where(Business.slug == slug)) is not None:
        raise OperatorError(f"Slug {slug!r} is already used by another business")

    return NewBusiness(name=name, slug=slug, admin_email=admin_email)


def create_business_with_admin(
    db: Session,
    *,
    name: str,
    slug: str,
    admin_email: str,
    admin_password: str,
) -> OnboardedBusiness:
    # Validated again here: the slug may have been taken
    # while the operator was typing the password.
    new = validate_new_business(db, name=name, slug=slug, admin_email=admin_email)
    check_password(admin_password)

    business = Business(name=new.name, slug=new.slug)
    admin = User(
        email=new.admin_email,
        hashed_password=hash_password(admin_password),
        business=business,
        role=ROLE_ADMIN,
    )

    db.add_all([business, admin])

    # One commit saves both rows or neither,
    # so a business never exists without its first administrator.
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        # The checks above can race with a concurrent onboarding;
        # the database constraints are the final guard.
        raise OperatorError(
            "The slug was taken while onboarding; "
            "nothing was created"
        ) from error

    return OnboardedBusiness(
        business_id=business.id,
        slug=business.slug,
        admin_user_id=admin.id,
        admin_email=admin.email,
    )
