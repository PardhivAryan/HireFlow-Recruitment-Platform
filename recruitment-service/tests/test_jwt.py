from datetime import datetime, timedelta, timezone

from fastapi import status
import jwt
import pytest

from app.config import settings


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/jobs", {"title": "Role", "description": "Work", "location": "Remote"}),
        ("get", "/jobs", None),
        ("get", "/jobs/1", None),
        ("put", "/jobs/1", {"title": "Role", "description": "Work", "location": "Remote"}),
        ("delete", "/jobs/1", None),
        ("post", "/jobs/1/apply", {}),
        ("get", "/applications/me", None),
        ("get", "/jobs/1/applications", None),
        ("patch", "/applications/1/status", {"status": "REJECTED"}),
    ],
)
def test_all_business_routes_require_authentication(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["Bearer invalid", "Basic invalid", "Bearer"])
def test_invalid_authorization_header(client, authorization):
    response = client.get("/jobs", headers={"Authorization": authorization})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        {"exp": None},
        {"exp": "not-a-time"},
        {"sub": "not-a-user-id"},
        {"sub": 123},
        {"sub": "-1"},
        {"sub": str(2**80)},
        {"role": "owner"},
        {"role": None},
    ],
)
def test_rejects_invalid_claims(client, changes):
    payload = {
        "sub": "21",
        "role": "candidate",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        **changes,
    }
    token = jwt.encode(payload, settings.auth_jwt_secret.get_secret_value(), algorithm="HS256")
    response = client.get("/jobs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("missing_claim", ["sub", "role", "exp"])
def test_required_claims(client, missing_claim):
    payload = {
        "sub": "21",
        "role": "candidate",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    del payload[missing_claim]
    token = jwt.encode(payload, settings.auth_jwt_secret.get_secret_value(), algorithm="HS256")
    response = client.get("/jobs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "none"])
def test_rejects_wrong_signature_or_algorithm(client, algorithm):
    key = settings.auth_jwt_secret.get_secret_value()
    if algorithm == "HS256":
        key = "a-different-signing-secret-" * 3
    if algorithm == "none":
        key = None
    token = jwt.encode(
        {"sub": "11", "role": "recruiter", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        key,
        algorithm=algorithm,
    )
    response = client.get("/jobs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_health_remains_public(client):
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"service": "recruitment-service", "status": "healthy"}
