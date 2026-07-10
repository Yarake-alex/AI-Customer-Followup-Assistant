import base64
import hashlib
import hmac
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import User


PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def create_user(
    db: Session,
    username: str,
    password: str,
    is_admin: bool = False,
    role: str = "user",
    is_active: bool = True,
) -> User:
    user = User(
        username=username.strip(),
        password_hash=hash_password(password),
        is_admin=is_admin,
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_bootstrap_admin(db: Session, username: str, password: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user:
        # Ensure existing admin has correct role/is_active
        updated = False
        if not user.role or user.role == "user":
            user.role = "admin"
            updated = True
        if user.is_active is None:
            user.is_active = True
            updated = True
        if user.is_admin and user.role != "admin":
            user.role = "admin"
            updated = True
        if updated:
            db.commit()
            db.refresh(user)
        return user

    is_first_user = db.query(User).count() == 0
    return create_user(
        db=db,
        username=username,
        password=password,
        is_admin=is_first_user,
        role="admin" if is_first_user else "user",
    )


def utc_timestamp() -> float:
    return datetime.now(timezone.utc).timestamp()
