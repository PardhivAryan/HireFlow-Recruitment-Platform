import jwt
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Role, User
from app.security import ALGORITHM, verify_password


@pytest.fixture
def recruiter_headers():
    return {"X-Recruiter-Creation-Secret": settings.recruiter_creation_secret.get_secret_value()}


def test_create_recruiter_and_login(client, db, registration, recruiter_headers):
    response = client.post(
        "/auth/recruiters",
        json={**registration, "name": " Test Recruiter ", "email": " RECRUITER@EXAMPLE.COM "},
        headers=recruiter_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert set(data) == {"id", "name", "email", "role", "created_at", "active"}
    assert data["name"] == "Test Recruiter"
    assert data["email"] == "recruiter@example.com"
    assert data["role"] == "recruiter"
    assert data["active"] is True
    user = db.get(User, data["id"])
    assert user.role == Role.recruiter
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(registration["password"], user.password_hash)
    assert registration["password"] not in response.text
    assert user.password_hash not in response.text
    assert settings.recruiter_creation_secret.get_secret_value() not in response.text

    login = client.post(
        "/auth/token", data={"username": data["email"], "password": registration["password"]}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    claims = jwt.decode(token, settings.auth_jwt_secret.get_secret_value(), algorithms=[ALGORITHM])
    assert claims["role"] == "recruiter"
    assert claims["sub"] == str(data["id"])
    me = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == data


@pytest.mark.parametrize("secret", [None, "", "incorrect-recruiter-secret"])
def test_secret_required(client, db, registration, secret):
    headers = {} if secret is None else {"X-Recruiter-Creation-Secret": secret}
    response = client.post("/auth/recruiters", json=registration, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid recruiter creation credentials"}
    assert db.scalar(select(User)) is None


def test_jwt_alone_cannot_create_recruiter(client, access_token, registration):
    response = client.post(
        "/auth/recruiters",
        headers={"Authorization": f"Bearer {access_token}"},
        json={**registration, "email": "recruiter@example.com"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("first_endpoint", ["/auth/register", "/auth/recruiters"])
def test_duplicate_email(client, db, registration, recruiter_headers, first_endpoint):
    first = client.post(first_endpoint, json=registration, headers=recruiter_headers)
    assert first.status_code == 201
    duplicate = client.post(
        "/auth/recruiters",
        json={**registration, "email": " CANDIDATE@EXAMPLE.COM "},
        headers=recruiter_headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Email already registered"}
    assert len(db.scalars(select(User)).all()) == 1
    assert db.get(User, first.json()["id"]).role.value == first.json()["role"]


def test_duplicate_email_database_constraint(client, db, registration, recruiter_headers, monkeypatch):
    assert client.post("/auth/recruiters", json=registration, headers=recruiter_headers).status_code == 201
    # Simulate another request inserting the email after the existence check.
    monkeypatch.setattr(db, "scalar", lambda statement: None)
    response = client.post("/auth/recruiters", json=registration, headers=recruiter_headers)
    assert response.status_code == 409


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"id": 999}, {"active": False}, {"password_hash": "untrusted-hash"}])
def test_only_name_email_password_accepted(client, db, registration, recruiter_headers, extra):
    response = client.post("/auth/recruiters", json={**registration, **extra}, headers=recruiter_headers)
    assert response.status_code == 422
    assert "untrusted-hash" not in response.text
    assert registration["password"] not in response.text
    assert db.scalar(select(User)) is None


@pytest.mark.parametrize("field", ["name", "email", "password"])
def test_body_fields_required(client, db, registration, recruiter_headers, field):
    del registration[field]
    response = client.post("/auth/recruiters", json=registration, headers=recruiter_headers)
    assert response.status_code == 422
    assert db.scalar(select(User)) is None


@pytest.mark.parametrize("changes", [{"name": "   "}, {"email": "invalid"}, {"password": "short"}])
def test_invalid_recruiter_body(client, db, registration, recruiter_headers, changes):
    response = client.post("/auth/recruiters", json={**registration, **changes}, headers=recruiter_headers)
    assert response.status_code == 422
    assert db.scalar(select(User)) is None


@pytest.mark.parametrize("role", ["recruiter", "admin"])
def test_public_registration_stays_candidate_only(client, registration, recruiter_headers, role):
    response = client.post("/auth/register", json={**registration, "role": role}, headers=recruiter_headers)
    assert response.status_code == 201
    assert response.json()["role"] == "candidate"
