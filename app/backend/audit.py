"""Records successful changes in audit_events, in the same transaction as the change."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.models import ACTOR_OPERATOR, ACTOR_USER, AuditEvent, Business, User


def record(
    db: Session,
    *,
    business: Business,
    actor: User | None,
    action: str,
    target: User | None = None,
    **details,
) -> None:
    # No actor means the operator's CLI. The caller commits, so a failure
    # after recording rolls back the change and its record together.
    db.add(
        AuditEvent(
            business_id=business.id,
            business_slug=business.slug,
            actor_kind=ACTOR_USER if actor else ACTOR_OPERATOR,
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            target_user_id=target.id if target else None,
            target_email=target.email if target else None,
            details=details,
        )
    )


def list_audit_events(db: Session, business_slug: str, limit: int) -> list[AuditEvent]:
    """The newest events first."""
    # By the copied slug, not the businesses table:
    # the history of a deleted business stays readable.
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.business_slug == business_slug.strip())
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        )
    )
