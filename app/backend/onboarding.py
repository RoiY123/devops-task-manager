import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.models import ROLE_ADMIN, Business, User
from app.backend.security import hash_password


# Same rule as the ck_businesses_slug_format database constraint,
# checked here first so the operator gets a readable message.
SLUG_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

MAX_NAME_LENGTH = 200
MAX_SLUG_LENGTH = 63
MAX_EMAIL_LENGTH = 320
MIN_ADMIN_PASSWORD_LENGTH = 12


class OnboardingError(ValueError):
    """Rejected onboarding input. The message is safe to show the operator."""


@dataclass(frozen=True)
class OnboardedBusiness:
    business_id: int
    slug: str
    admin_user_id: int
    admin_email: str


def normalize_name(name: str) -> str:
    # Identical-looking Hebrew can arrive as different Unicode sequences
    # (for example, nikud marks typed in a different order);
    # NFC stores it one canonical way so duplicate checks and searches match.
    return unicodedata.normalize("NFC", name).strip()


def create_business_with_admin(
    db: Session,
    *,
    name: str,
    slug: str,
    admin_email: str,
    admin_password: str,
) -> OnboardedBusiness:
    name = normalize_name(name)
    slug = slug.strip()
    admin_email = admin_email.strip()

    if not name:
        raise OnboardingError("Business name must not be empty")

    if len(name) > MAX_NAME_LENGTH:
        raise OnboardingError(
            f"Business name must be at most {MAX_NAME_LENGTH} characters"
        )

    if len(slug) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise OnboardingError(
            f"Slug {slug!r} is invalid: use lowercase letters, digits and "
            f"single hyphens, at most {MAX_SLUG_LENGTH} characters"
        )

    if "@" not in admin_email or len(admin_email) > MAX_EMAIL_LENGTH:
        raise OnboardingError(f"Admin email {admin_email!r} is invalid")

    if len(admin_password) < MIN_ADMIN_PASSWORD_LENGTH:
        raise OnboardingError(
            f"Admin password must be at least "
            f"{MIN_ADMIN_PASSWORD_LENGTH} characters"
        )

    if db.scalar(select(Business.id).where(Business.slug == slug)) is not None:
        raise OnboardingError(f"Slug {slug!r} is already used by another business")

    # Email is still unique across all businesses until business-specific login exists.
    if db.scalar(select(User.id).where(User.email == admin_email)) is not None:
        raise OnboardingError(f"Email {admin_email!r} is already registered")

    business = Business(name=name, slug=slug)
    admin = User(
        email=admin_email,
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
        raise OnboardingError(
            "The slug or admin email was taken while onboarding; "
            "nothing was created"
        ) from error

    return OnboardedBusiness(
        business_id=business.id,
        slug=business.slug,
        admin_user_id=admin.id,
        admin_email=admin.email,
    )
