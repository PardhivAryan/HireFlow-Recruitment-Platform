from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError

from app.config import settings
from app.database import DbSession
from app.models import Role, User
from app.security import ALGORITHM


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.auth_jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "role", "exp"]},
        )
        user_id = int(payload["sub"])
        role = Role(payload["role"])
        # User IDs use a PostgreSQL INTEGER column.
        if not 0 < user_id <= 2_147_483_647:
            raise ValueError("Invalid user ID")
    except (InvalidTokenError, ValueError, TypeError):
        raise unauthorized from None

    user = db.get(User, user_id)
    if user is None or not user.active or user.role != role:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: Role):
    def check_role(user: CurrentUser) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return user

    return check_role


def require_recruiter_creation_secret(
    secret: Annotated[str | None, Header(alias="X-Recruiter-Creation-Secret")] = None,
) -> None:
    expected = settings.recruiter_creation_secret.get_secret_value()
    if secret is None or not compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid recruiter creation credentials",
        )
