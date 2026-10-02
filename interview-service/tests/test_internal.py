from fastapi import status
import pytest
from sqlalchemy import select

from app.models import InterviewDB


@pytest.mark.parametrize("secret", [None, "", "invalid-service-secret"])
def test_rejects_invalid_internal_secret(client, db, auth_headers, interview_data, secret):
    headers = auth_headers(99, "admin")
    if secret is not None:
        headers["X-Internal-Service-Secret"] = secret
    response = client.post("/internal/interviews", json=interview_data, headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert db.scalar(select(InterviewDB)) is None


def test_internal_creation_starts_pending(client, internal_headers, interview_data):
    response = client.post("/internal/interviews", json=interview_data, headers=internal_headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["application_id"] == interview_data["application_id"]
    assert data["candidate_id"] == interview_data["candidate_id"]
    assert data["recruiter_id"] == interview_data["recruiter_id"]
    assert data["status"] == "PENDING"
    assert data["interview_type"] == "VIDEO"
    assert data["scheduled_at"] is None
    assert data["meeting_link"] is None
    assert data["feedback"] is None
    assert data["created_at"]


def test_duplicate_creation_returns_existing_without_reset(client, db, internal_headers, auth_headers, interview_data, interview):
    changed = client.post(
        f"/interviews/{interview['id']}/feedback",
        json={"feedback": "Keep this feedback"},
        headers=auth_headers(),
    ).json()
    response = client.post("/internal/interviews", json=interview_data, headers=internal_headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == changed
    assert len(db.scalars(select(InterviewDB)).all()) == 1


@pytest.mark.parametrize("field", ["candidate_id", "recruiter_id"])
def test_existing_interview_cannot_be_reassigned(client, internal_headers, interview_data, interview, field):
    response = client.post(
        "/internal/interviews", json={**interview_data, field: 999}, headers=internal_headers
    )
    assert response.status_code == status.HTTP_409_CONFLICT


def test_unique_constraint_handles_concurrent_duplicate(client, db, internal_headers, interview_data, interview, monkeypatch):
    original_scalar = db.scalar
    calls = 0

    def miss_first_select(statement):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_scalar(statement)

    monkeypatch.setattr(db, "scalar", miss_first_select)
    response = client.post("/internal/interviews", json=interview_data, headers=internal_headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == interview
    assert len(db.scalars(select(InterviewDB)).all()) == 1


@pytest.mark.parametrize("changes", [{"application_id": 0}, {"candidate_id": -1}, {"recruiter_id": 2**80}, {"status": "COMPLETED"}])
def test_invalid_internal_payload(client, internal_headers, interview_data, changes):
    response = client.post(
        "/internal/interviews", json={**interview_data, **changes}, headers=internal_headers
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_no_public_interview_creation(client, auth_headers, interview_data):
    response = client.post("/interviews", json=interview_data, headers=auth_headers())
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
