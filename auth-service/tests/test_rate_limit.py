import time
from unittest.mock import Mock

import pytest
from redis.exceptions import ConnectionError, TimeoutError
from sqlalchemy import func, select

from app.config import settings
from app.main import app
from app.models import User
from app.rate_limit import get_redis


def login_attempt(client):
    return client.post(
        "/auth/token", data={"username": "missing@example.com", "password": "wrong-password"}
    )


def register_attempt(client, number):
    return client.post(
        "/auth/register",
        json={
            "name": "Candidate",
            "email": f"candidate{number}@example.com",
            "password": "correct-horse-battery",
        },
    )


@pytest.mark.parametrize("action", ["login", "register"])
def test_requests_below_limit_then_exceeded(client, db, action):
    for number in range(5):
        response = login_attempt(client) if action == "login" else register_attempt(client, number)
        assert response.status_code == (401 if action == "login" else 201)
        assert "Retry-After" not in response.headers

    blocked = login_attempt(client) if action == "login" else register_attempt(client, 5)
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert db.scalar(select(func.count()).select_from(User)) == (0 if action == "login" else 5)


@pytest.mark.parametrize("action", ["login", "register"])
def test_expiration_resets_counter(client, redis_store, monkeypatch, action):
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 1)
    monkeypatch.setattr(settings, f"auth_{action}_rate_limit", 1)
    first = login_attempt(client) if action == "login" else register_attempt(client, 0)
    assert first.status_code == (401 if action == "login" else 201)
    blocked = login_attempt(client) if action == "login" else register_attempt(client, 1)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "1"

    time.sleep(1.1)
    assert not redis_store.exists(f"{settings.auth_rate_limit_prefix}:{action}:testclient")
    reset = login_attempt(client) if action == "login" else register_attempt(client, 2)
    assert reset.status_code == (401 if action == "login" else 201)


def test_later_attempt_does_not_extend_window(client, redis_store):
    assert login_attempt(client).status_code == 401
    key = f"{settings.auth_rate_limit_prefix}:login:testclient"
    redis_store.expire(key, 10)
    assert login_attempt(client).status_code == 401
    assert 0 < redis_store.ttl(key) <= 10
    assert redis_store.get(key) == "2"


def test_login_and_registration_have_separate_counters(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_login_rate_limit", 1)
    monkeypatch.setattr(settings, "auth_register_rate_limit", 1)
    assert login_attempt(client).status_code == 401
    assert login_attempt(client).status_code == 429
    assert register_attempt(client, 0).status_code == 201
    assert register_attempt(client, 1).status_code == 429


def test_successful_login_also_counts(client, registered_user, registration, monkeypatch):
    monkeypatch.setattr(settings, "auth_login_rate_limit", 1)
    data = {"username": registration["email"], "password": registration["password"]}
    assert client.post("/auth/token", data=data).status_code == 200
    assert client.post("/auth/token", data=data).status_code == 429


def test_forwarded_header_cannot_bypass_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_login_rate_limit", 1)
    assert login_attempt(client).status_code == 401
    response = client.post(
        "/auth/token",
        data={"username": "another@example.com", "password": "wrong-password"},
        headers={"X-Forwarded-For": "203.0.113.2", "Forwarded": "for=203.0.113.2"},
    )
    assert response.status_code == 429


@pytest.mark.parametrize("error", [ConnectionError, TimeoutError])
@pytest.mark.parametrize("path", ["/auth/token", "/auth/register"])
def test_redis_failure_returns_generic_503(client, registration, error, path):
    redis = Mock()
    redis.pipeline.side_effect = error("redis://private-user:private-password@private-host")
    app.dependency_overrides[get_redis] = lambda: redis
    if path == "/auth/token":
        response = login_attempt(client)
    else:
        response = client.post(path, json=registration)
    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication rate limiting is temporarily unavailable"}
    assert "private-password" not in response.text


def test_invalid_registration_does_not_echo_password(client, registration):
    registration["password"] = "private-password-" * 100
    response = client.post("/auth/register", json=registration)
    assert response.status_code == 422
    assert "private-password" not in response.text
    for error in response.json()["detail"]:
        assert set(error) == {"loc", "msg", "type"}


def test_invalid_body_does_not_echo_password_hash(client):
    response = client.post("/auth/register", json=[{"password_hash": "private-hash"}])
    assert response.status_code == 422
    assert "private-hash" not in response.text
