from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import Base, DbSession, engine
from app.dependencies import CurrentUser, require_recruiter_creation_secret
from app.models import Role, User
from app.rate_limit import limit_login, limit_registration
from app.schemas import RecruiterCreate, TokenResponse, UserRegister, UserResponse
from app.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="HireFlow Auth Service", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
def validation_error_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default errors include input values, which can expose passwords.
    errors = [
        {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": errors}
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "auth-service", "status": "healthy"}


@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_registration)],
)
def register(data: UserRegister, db: DbSession):
    if db.scalar(select(User).where(User.email == data.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        **data.model_dump(exclude={"password"}),
        password_hash=hash_password(data.password),
        role=Role.candidate,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # PostgreSQL also prevents duplicates from simultaneous registrations.
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from None
        raise
    db.refresh(user)
    return user


@app.post(
    "/auth/recruiters",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_recruiter_creation_secret)],
)
def create_recruiter(data: RecruiterCreate, db: DbSession):
    if db.scalar(select(User).where(User.email == data.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    user = User(
        **data.model_dump(exclude={"password"}),
        password_hash=hash_password(data.password),
        role=Role.recruiter,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # PostgreSQL also prevents duplicates from simultaneous registrations.
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from None
        raise
    db.refresh(user)
    return user


@app.post("/auth/token", response_model=TokenResponse, dependencies=[Depends(limit_login)])
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession):
    email = form.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    stored_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(form.password, stored_hash)
    if user is None or not password_valid or not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user))


@app.get("/users/me", response_model=UserResponse)
def read_current_user(user: CurrentUser):
    return user
