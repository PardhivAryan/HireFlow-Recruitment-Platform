from datetime import datetime

from fastapi import status
import pytest
from sqlalchemy import select

from app.models import ApplicationDB, ApplicationStatus


def test_apply_uses_candidate_from_token(client, auth_headers, job):
    response = client.post(
        f"/jobs/{job['id']}/apply",
        json={"candidate_id": 999, "job_id": 999, "status": "SHORTLISTED", "cover_note": "My experience"},
        headers=auth_headers(21, "candidate"),
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["candidate_id"] == 21
    assert data["job_id"] == job["id"]
    assert data["status"] == "APPLIED"
    assert data["cover_note"] == "My experience"
    assert datetime.fromisoformat(data["applied_at"]).tzinfo is not None


def test_apply_without_cover_note(client, auth_headers, job):
    response = client.post(f"/jobs/{job['id']}/apply", headers=auth_headers(21, "candidate"))
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["cover_note"] is None


def test_duplicate_application(client, db, auth_headers, job, application):
    response = client.post(f"/jobs/{job['id']}/apply", headers=auth_headers(21, "candidate"))
    assert response.status_code == status.HTTP_409_CONFLICT
    assert len(db.scalars(select(ApplicationDB)).all()) == 1


def test_database_prevents_duplicate_after_precheck(client, db, auth_headers, job, application, monkeypatch):
    # Simulate the competing insert winning after our duplicate check.
    monkeypatch.setattr(db, "scalar", lambda statement: None)
    response = client.post(f"/jobs/{job['id']}/apply", headers=auth_headers(21, "candidate"))
    assert response.status_code == status.HTTP_409_CONFLICT
    assert len(db.scalars(select(ApplicationDB)).all()) == 1


def test_candidates_only_see_own_applications(client, auth_headers, job, application):
    second = client.post(
        f"/jobs/{job['id']}/apply", headers=auth_headers(22, "candidate")
    )
    assert second.status_code == status.HTTP_201_CREATED
    assert client.get("/applications/me", headers=auth_headers(21, "candidate")).json() == [application]
    assert client.get("/applications/me", headers=auth_headers(22, "candidate")).json() == [second.json()]
    assert client.get("/applications/me", headers=auth_headers(23, "candidate")).json() == []


def test_candidate_can_apply_to_different_jobs(client, auth_headers, job_data, application):
    other_job = client.post("/jobs", json=job_data, headers=auth_headers()).json()
    response = client.post(f"/jobs/{other_job['id']}/apply", headers=auth_headers(21, "candidate"))
    assert response.status_code == status.HTTP_201_CREATED
    assert len(client.get("/applications/me", headers=auth_headers(21, "candidate")).json()) == 2


@pytest.mark.parametrize("role", ["recruiter", "admin"])
def test_only_candidates_can_apply_or_use_me(client, auth_headers, job, role):
    headers = auth_headers(99, role)
    assert client.post(f"/jobs/{job['id']}/apply", headers=headers).status_code == status.HTTP_403_FORBIDDEN
    assert client.get("/applications/me", headers=headers).status_code == status.HTTP_403_FORBIDDEN


def test_inactive_job_rejects_applications(client, db, auth_headers, job):
    client.delete(f"/jobs/{job['id']}", headers=auth_headers())
    response = client.post(f"/jobs/{job['id']}/apply", headers=auth_headers(21, "candidate"))
    assert response.status_code == status.HTTP_409_CONFLICT
    assert db.scalar(select(ApplicationDB)) is None


def test_missing_job_cannot_be_applied_to(client, auth_headers):
    response = client.post("/jobs/2147483647/apply", headers=auth_headers(21, "candidate"))
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("actor", [(11, "recruiter"), (99, "admin")])
def test_owner_and_admin_can_read_applicants(client, auth_headers, job, application, actor):
    response = client.get(f"/jobs/{job['id']}/applications", headers=auth_headers(*actor))
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [application]


@pytest.mark.parametrize("actor", [(21, "candidate"), (12, "recruiter")])
def test_other_users_cannot_read_or_update_applications(client, db, auth_headers, job, application, actor):
    headers = auth_headers(*actor)
    assert client.get(f"/jobs/{job['id']}/applications", headers=headers).status_code == status.HTTP_403_FORBIDDEN
    response = client.patch(
        f"/applications/{application['id']}/status", json={"status": "SHORTLISTED"}, headers=headers
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert db.get(ApplicationDB, application["id"]).status == ApplicationStatus.APPLIED


@pytest.mark.parametrize("actor", [(11, "recruiter"), (99, "admin")])
@pytest.mark.parametrize("new_status", list(ApplicationStatus))
def test_owner_and_admin_update_status(client, auth_headers, job, application, actor, new_status):
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": new_status.value, "candidate_id": 999, "job_id": 999, "cover_note": "Changed"},
        headers=auth_headers(*actor),
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {**application, "status": new_status.value}
    assert client.get(
        "/applications/me", headers=auth_headers(21, "candidate")
    ).json() == [response.json()]


def test_closed_job_keeps_manageable_application_history(client, auth_headers, job, application):
    client.delete(f"/jobs/{job['id']}", headers=auth_headers())
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": "REJECTED"},
        headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_200_OK
    assert client.get(
        f"/jobs/{job['id']}/applications", headers=auth_headers()
    ).json() == [response.json()]


def test_invalid_status(client, db, auth_headers, application):
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": "HIRED"},
        headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert db.get(ApplicationDB, application["id"]).status == ApplicationStatus.APPLIED


def test_missing_application_and_job_applicant_list(client, auth_headers):
    assert client.patch(
        "/applications/2147483647/status",
        json={"status": "SHORTLISTED"},
        headers=auth_headers(),
    ).status_code == status.HTTP_404_NOT_FOUND
    assert client.get(
        "/jobs/2147483647/applications", headers=auth_headers()
    ).status_code == status.HTTP_404_NOT_FOUND
