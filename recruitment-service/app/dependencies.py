from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel

from app.config import settings


class Role(str, Enum):
    candidate = "candidate"
    recruiter = "recruiter"
    admin = "admin"


class AuthenticatedUser(BaseModel):
    id: int
    role: Role


# Auth issues OAuth2 bearer tokens. Here we accept an existing token, including in /docs.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.auth_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["sub", "role", "exp"]},
        )
        user_id = int(payload["sub"])
        role = Role(payload["role"])
        # IDs issued by Auth fit its PostgreSQL INTEGER primary key.
        if not 0 < user_id <= 2_147_483_647:
            raise ValueError("Invalid user ID")
    except (InvalidTokenError, ValueError, TypeError, OverflowError):
        raise unauthorized from None
    return AuthenticatedUser(id=user_id, role=role)


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def require_roles(*allowed_roles: Role):
    def check_role(user: CurrentUser) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return user

    return check_role


RecruiterOrAdmin = Annotated[
    AuthenticatedUser, Depends(require_roles(Role.recruiter, Role.admin))
]
CandidateUser = Annotated[AuthenticatedUser, Depends(require_roles(Role.candidate))]
