from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app import main
from app.config import settings
from app.database import Base, get_db


@pytest.fixture(scope="session")
def test_engine():
    url = make_url(os.environ.get("INTERVIEW_TEST_DATABASE_URL") or settings.database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Interview tests require PostgreSQL")
    url = url.set(drivername="postgresql+psycopg")
    schema = f"interview_test_{uuid4().hex}"
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
    # Match Auth's tests: endpoint commits cannot commit the outer test transaction.
    with test_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def client(db, test_engine, monkeypatch):
    def override_get_db():
        yield db

    monkeypatch.setattr(main, "engine", test_engine)
    main.app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
def auth_headers():
    def headers(user_id=11, role="recruiter"):
        token = jwt.encode(
            {
                "sub": str(user_id),
                "role": role,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            settings.auth_jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}
    return headers


@pytest.fixture
def internal_headers():
    return {"X-Internal-Service-Secret": settings.internal_service_secret.get_secret_value()}


@pytest.fixture
def interview_data():
    return {"application_id": 101, "candidate_id": 21, "recruiter_id": 11}


@pytest.fixture
def interview(client, internal_headers, interview_data):
    response = client.post("/internal/interviews", json=interview_data, headers=internal_headers)
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()
