import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app import main
from app.config import settings
from app.database import Base, get_db
from app.rate_limit import get_redis


@pytest.fixture(scope="session")
def test_engine():
    url = make_url(os.environ.get("AUTH_TEST_DATABASE_URL") or settings.database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Auth tests require PostgreSQL")
    url = url.set(drivername="postgresql+psycopg")
    schema = f"auth_test_{uuid4().hex}"
    admin_engine = create_engine(url)
    with admin_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


@pytest.fixture
def db(test_engine):
    # Endpoint commits release savepoints; the outer transaction isolates each test.
    with test_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def redis_store(monkeypatch):
    # Use real Redis, but isolate and clean up only this test's keys.
    prefix = f"hireflow:rate-limit:test:{uuid4().hex}"
    monkeypatch.setattr(settings, "auth_rate_limit_prefix", prefix)
    monkeypatch.setattr(settings, "auth_login_rate_limit", 5)
    monkeypatch.setattr(settings, "auth_register_rate_limit", 5)
    monkeypatch.setattr(settings, "auth_rate_limit_window_seconds", 60)
    store = Redis.from_url(
        os.environ.get("AUTH_TEST_REDIS_URL") or settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    store.ping()
    try:
        yield store
    finally:
        keys = list(store.scan_iter(match=f"{prefix}:*"))
        if keys:
            store.delete(*keys)
        store.close()


@pytest.fixture
def client(db, test_engine, redis_store, monkeypatch):
    def override_get_db():
        yield db

    monkeypatch.setattr(main, "engine", test_engine)
    main.app.dependency_overrides[get_db] = override_get_db
    main.app.dependency_overrides[get_redis] = lambda: redis_store
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
def registration():
    return {
        "name": "Test Candidate",
        "email": "candidate@example.com",
        "password": "correct-horse-battery",
    }


@pytest.fixture
def registered_user(client, registration):
    response = client.post("/auth/register", json=registration)
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def access_token(client, registered_user, registration):
    response = client.post(
        "/auth/token",
        data={"username": registration["email"], "password": registration["password"]},
    )
    assert response.status_code == 200
    return response.json()["access_token"]
