from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.config import settings
from app.models import User


ALGORITHM = "HS256"
password_hasher = PasswordHash((Argon2Hasher(),))
# Missing users still perform one password verification, like a wrong password.
DUMMY_PASSWORD_HASH = password_hasher.hash("unused-login-timing-placeholder")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.auth_access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": str(user.id), "role": user.role.value, "exp": expires_at},
        settings.auth_jwt_secret.get_secret_value(),
        algorithm=ALGORITHM,
    )
