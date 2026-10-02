from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.dependencies import require_roles
from app.models import Role, User
from app.security import ALGORITHM, create_access_token, verify_password


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_registration(client, db, registration):
    response = client.post("/auth/register", json=registration)

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == registration["name"]
    assert data["email"] == registration["email"]
    assert data["role"] == "candidate"
    assert data["active"] is True
    assert datetime.fromisoformat(data["created_at"]).tzinfo is not None
    stored = db.get(User, data["id"])
    assert stored.password_hash.startswith("$argon2id$")
    assert stored.password_hash != registration["password"]
    assert verify_password(registration["password"], stored.password_hash)


@pytest.mark.parametrize("requested_role", ["recruiter", "admin"])
def test_registration_cannot_assign_privileged_fields(client, registration, requested_role):
    response = client.post(
        "/auth/register",
        json={**registration, "role": requested_role, "active": False, "id": 999},
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["role"] == "candidate"
    assert response.json()["active"] is True
    assert response.json()["id"] != 999


def test_duplicate_email(client, registered_user, registration):
    response = client.post(
        "/auth/register", json={**registration, "email": " CANDIDATE@EXAMPLE.COM "}
    )
    assert response.status_code == status.HTTP_409_CONFLICT


def test_duplicate_email_database_constraint(client, db, registered_user, registration, monkeypatch):
    # Simulate another request inserting the email after the existence check.
    monkeypatch.setattr(db, "scalar", lambda statement: None)
    response = client.post("/auth/register", json=registration)
    assert response.status_code == status.HTTP_409_CONFLICT
    assert client.get("/health").status_code == status.HTTP_200_OK


def test_password_not_exposed(client, db, registered_user, access_token, registration):
    me = client.get("/users/me", headers=bearer(access_token))
    stored = db.get(User, registered_user["id"])
    for data in (registered_user, me.json()):
        assert set(data) == {"id", "name", "email", "role", "created_at", "active"}
        assert "password" not in data
        assert "password_hash" not in data
        assert registration["password"] not in str(data)
        assert stored.password_hash not in str(data)


def test_valid_login(client, registered_user, registration):
    before = datetime.now(timezone.utc)
    response = client.post(
        "/auth/token",
        data={"username": " CANDIDATE@EXAMPLE.COM ", "password": registration["password"]},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert set(data) == {"access_token", "token_type"}
    assert data["token_type"] == "bearer"
    payload = jwt.decode(
        data["access_token"], settings.auth_jwt_secret.get_secret_value(), algorithms=[ALGORITHM]
    )
    assert set(payload) == {"sub", "role", "exp"}
    assert payload["sub"] == str(registered_user["id"])
    assert payload["role"] == "candidate"
    expected = before + timedelta(minutes=settings.auth_access_token_expire_minutes)
    assert abs(payload["exp"] - expected.timestamp()) < 5


@pytest.mark.parametrize(
    ("email", "password"),
    [("candidate@example.com", "wrong-password"), ("missing@example.com", "any-password")],
)
def test_invalid_credentials(client, registered_user, email, password):
    response = client.post("/auth/token", data={"username": email, "password": password})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Incorrect email or password"}


@pytest.mark.parametrize("headers", [{}, bearer("not-a-jwt"), {"Authorization": "Basic invalid"}])
def test_protected_endpoint_requires_token(client, headers):
    response = client.get("/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


def test_protected_endpoint_with_valid_token(client, registered_user, access_token):
    response = client.get("/users/me", headers=bearer(access_token))
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == registered_user


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        {"sub": "not-an-id"},
        {"sub": "-1"},
        {"sub": str(2**80)},
        {"sub": "2147483647"},
        {"role": "owner"},
        {"role": "admin"},
        {"role": None},
        {"exp": None},
    ],
)
def test_invalid_token_claims(client, registered_user, changes):
    payload = {
        "sub": str(registered_user["id"]),
        "role": "candidate",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        **changes,
    }
    token = jwt.encode(payload, settings.auth_jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    response = client.get("/users/me", headers=bearer(token))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("missing_claim", ["sub", "role", "exp"])
def test_token_requires_all_claims(client, registered_user, missing_claim):
    payload = {
        "sub": str(registered_user["id"]),
        "role": "candidate",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    del payload[missing_claim]
    token = jwt.encode(payload, settings.auth_jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    assert client.get("/users/me", headers=bearer(token)).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("algorithm", ["HS256", "HS384"])
def test_rejects_wrong_signature_or_algorithm(client, registered_user, algorithm):
    payload = {
        "sub": str(registered_user["id"]),
        "role": "candidate",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    key = settings.auth_jwt_secret.get_secret_value() if algorithm == "HS384" else "a-different-secret-" * 4
    token = jwt.encode(payload, key, algorithm=algorithm)
    assert client.get("/users/me", headers=bearer(token)).status_code == status.HTTP_401_UNAUTHORIZED


def test_inactive_user_cannot_login_or_use_token(client, db, registered_user, access_token, registration):
    user = db.get(User, registered_user["id"])
    user.active = False
    db.commit()
    response = client.post(
        "/auth/token",
        data={"username": registration["email"], "password": registration["password"]},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/users/me", headers=bearer(access_token)).status_code == status.HTTP_401_UNAUTHORIZED


def test_deleted_user_token_rejected(client, db, registered_user, access_token):
    db.delete(db.get(User, registered_user["id"]))
    db.commit()
    assert client.get("/users/me", headers=bearer(access_token)).status_code == status.HTTP_401_UNAUTHORIZED


def test_role_change_invalidates_old_token(client, db, registered_user, access_token):
    user = db.get(User, registered_user["id"])
    user.role = Role.recruiter
    db.commit()
    assert client.get("/users/me", headers=bearer(access_token)).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("user_role", list(Role))
@pytest.mark.parametrize("allowed_role", list(Role))
def test_role_dependency(db, client, registered_user, user_role, allowed_role):
    user = db.get(User, registered_user["id"])
    user.role = user_role
    db.commit()
    token = create_access_token(user)
    role_app = FastAPI()

    def override_get_db():
        yield db

    role_app.dependency_overrides[get_db] = override_get_db

    @role_app.get("/restricted")
    def restricted(user: Annotated[User, Depends(require_roles(allowed_role))]):
        return {"id": user.id}

    with TestClient(role_app) as role_client:
        response = role_client.get("/restricted", headers=bearer(token))
    expected = status.HTTP_200_OK if user_role == allowed_role else status.HTTP_403_FORBIDDEN
    assert response.status_code == expected


def test_role_dependency_accepts_multiple_roles(db, registered_user):
    user = db.get(User, registered_user["id"])
    check = require_roles(Role.recruiter, Role.admin)
    for role in (Role.recruiter, Role.admin):
        user.role = role
        assert check(user) is user


@pytest.mark.parametrize(
    "changes",
    [{"name": "   "}, {"email": "not-an-email"}, {"password": "short"}],
)
def test_invalid_registration(client, db, registration, changes):
    response = client.post("/auth/register", json={**registration, **changes})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert db.scalar(select(User)) is None
