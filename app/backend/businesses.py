"""Business rules and the operator's business-management actions."""
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.accounts import OperatorError, get_business, reject_control_characters
from app.backend.models import Business, User


# Same rule as the ck_businesses_slug_format database constraint,
# checked here first so the operator gets a readable message.
SLUG_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

MAX_NAME_LENGTH = 200
MAX_SLUG_LENGTH = 63


def normalize_name(name: str) -> str:
    # Identical-looking Hebrew can arrive as different Unicode sequences
    # (for example, nikud marks typed in a different order);
    # NFC stores it one canonical way so duplicate checks and searches match.
    return unicodedata.normalize("NFC", name).strip()


def clean_business_name(name: str) -> str:
    name = normalize_name(name)
    reject_control_characters(name, "Business name")

    if not name:
        raise OperatorError("Business name must not be empty")

    if len(name) > MAX_NAME_LENGTH:
        raise OperatorError(
            f"Business name must be at most {MAX_NAME_LENGTH} characters"
        )

    return name


def clean_slug(slug: str) -> str:
    slug = slug.strip()

    if len(slug) > MAX_SLUG_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise OperatorError(
            f"Slug {slug!r} is invalid: use lowercase letters, digits and "
            f"single hyphens, at most {MAX_SLUG_LENGTH} characters"
        )

    return slug


def rename_business(db: Session, *, slug: str, name: str) -> str:
    """Change the display name only and return the previous one.

    The slug is not renamable: it will become the business's login URL.
    """
    business = get_business(db, slug)
    name = clean_business_name(name)
    previous = business.name

    business.name = name
    db.commit()

    return previous


def ensure_business_is_empty(db: Session, business: Business) -> None:
    user_count = db.scalar(
        select(func.count()).select_from(User).where(User.business_id == business.id)
    )

    if user_count > 0:
        raise OperatorError(
            f"Business {business.slug!r} has {user_count} users; remove them first"
        )


def delete_business(db: Session, *, slug: str) -> None:
    business = get_business(db, slug)
    ensure_business_is_empty(db, business)

    db.delete(business)

    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        # A user added after the check above; the RESTRICT foreign key refused.
        raise OperatorError(
            f"Business {slug.strip()!r} gained users while deleting; nothing was deleted"
        ) from error
