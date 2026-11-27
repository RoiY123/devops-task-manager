import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from pwdlib import PasswordHash

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.backend.database import get_db
from app.backend.models import User

load_dotenv()

password_hash = PasswordHash.recommended()

# Checked when no user matches, so a failed login takes as long whether or not
# the account exists and response times do not reveal which emails are registered.
DUMMY_PASSWORD_HASH = password_hash.hash("not-a-real-password")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)

if JWT_SECRET_KEY is None:
    raise RuntimeError("JWT_SECRET_KEY environment variable is not set")

bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_login_password(plain_password: str, hashed_password: str | None) -> bool:
    """Checks a login password, spending the same time when there is no user."""
    if hashed_password is None:
        password_hash.verify(plain_password, DUMMY_PASSWORD_HASH)
        return False

    return password_hash.verify(plain_password, hashed_password)


# Lowercase letters and digits without look-alikes (i, l, o, 0, 1): easy to read out and type.
TEMPORARY_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_temporary_password() -> str:
    """Four groups of four random characters, about 79 bits, for example k7rm-q2xa-9fhp-w3nc."""
    groups = (
        "".join(secrets.choice(TEMPORARY_PASSWORD_ALPHABET) for _ in range(4)) for _ in range(4)
    )
    return "-".join(groups)


def temporary_password_expired(user: User) -> bool:
    expires_at = user.temporary_password_expires_at
    return expires_at is not None and expires_at <= datetime.now(timezone.utc)


def create_access_token(
    user_id: int,
    expires_delta: timedelta | None = None,
) -> str:
    issued_at = datetime.now(timezone.utc)
    expiration = issued_at + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    payload = {
        "sub": str(user_id),
        # Compared with users.tokens_valid_after on every request.
        "iat": issued_at,
        "exp": expiration,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def token_was_cut_off(user: User, issued_at: int | None) -> bool:
    """Whether the user's logins were ended after this token was issued."""
    if user.tokens_valid_after is None:
        return False
    # Tokens from images before iat existed cannot prove they are newer.
    if issued_at is None:
        return True
    # iat holds whole seconds, so the cut-off is compared at that precision;
    # the fresh token issued in the same second as a password change stays valid.
    return issued_at < int(user.tokens_valid_after.timestamp())


def get_token_user(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        db: Session = Depends(get_db),
) -> User:
    """The user the login token names, even if they must first change their password."""
    credentials_exception =  HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        subject = payload.get("sub")

        if subject is None:
            raise credentials_exception
        
        user_id = int(subject)
        issued_at = payload.get("iat")

    except (jwt.InvalidTokenError, ValueError):
        raise credentials_exception

    user = db.get(User, user_id)

    if user is None or token_was_cut_off(user, issued_at):
        raise credentials_exception

    return user


def get_current_user(user: User = Depends(get_token_user)) -> User:
    """The logged-in user. Endpoints use this unless a temporary password may reach them."""
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Change your temporary password first",
        )

    return user
