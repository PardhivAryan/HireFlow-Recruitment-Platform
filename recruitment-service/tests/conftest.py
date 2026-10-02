from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4
from unittest.mock import Mock

from fastapi import status
from fastapi.testclient import TestClient
import httpx
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
    url = make_url(os.environ.get("RECRUITMENT_TEST_DATABASE_URL") or settings.database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Recruitment tests require PostgreSQL")
    url = url.set(drivername="postgresql+psycopg")
    schema = f"recruitment_test_{uuid4().hex}"
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
def client(db, test_engine, monkeypatch, interview_post):
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
def job_data():
    return {
        "title": "Python Developer",
        "description": "Build recruitment APIs.",
        "required_skills": ["Python", "FastAPI"],
        "location": "Hyderabad",
        "experience_required": 2,
        "salary_min": "50000.00",
        "salary_max": "80000.00",
        "active": True,
    }


@pytest.fixture
def job(client, auth_headers, job_data):
    response = client.post("/jobs", json=job_data, headers=auth_headers())
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


@pytest.fixture
def application(client, auth_headers, job):
    response = client.post(
        f"/jobs/{job['id']}/apply",
        json={"cover_note": "I have relevant Python experience."},
        headers=auth_headers(21, "candidate"),
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


@pytest.fixture
def interview_post(monkeypatch):
    def created(url, **kwargs):
        return httpx.Response(status.HTTP_201_CREATED, json={"id": 1, **kwargs["json"]})

    post = Mock(side_effect=created)
    monkeypatch.setattr("app.interview_client.httpx.post", post)
    return post
