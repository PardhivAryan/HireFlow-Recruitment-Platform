from datetime import datetime

from fastapi import status
import pytest
from sqlalchemy import select

from app.models import ApplicationDB, JobDB


@pytest.mark.parametrize("role", ["recruiter", "admin"])
def test_create_job_uses_token_owner(client, db, auth_headers, job_data, role):
    response = client.post(
        "/jobs",
        json={**job_data, "recruiter_id": 999, "id": 999},
        headers=auth_headers(11, role),
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["recruiter_id"] == 11
    assert data["id"] != 999
    assert data["required_skills"] == ["Python", "FastAPI"]
    assert data["salary_min"] == "50000.00"
    assert datetime.fromisoformat(data["created_at"]).tzinfo is not None
    assert db.get(JobDB, data["id"]).title == job_data["title"]


@pytest.mark.parametrize("role", ["candidate", "recruiter", "admin"])
def test_read_jobs(client, auth_headers, job, role):
    headers = auth_headers(31, role)
    assert client.get("/jobs", headers=headers).json() == [job]
    response = client.get(f"/jobs/{job['id']}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == job


def test_candidate_cannot_create_job(client, db, auth_headers, job_data):
    response = client.post("/jobs", json=job_data, headers=auth_headers(21, "candidate"))
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert db.scalar(select(JobDB)) is None


def test_owner_update_and_full_replacement(client, auth_headers, job):
    response = client.put(
        f"/jobs/{job['id']}",
        headers=auth_headers(),
        json={
            "title": " Senior Developer ",
            "description": "New responsibilities",
            "location": "Remote",
            "recruiter_id": 999,
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["title"] == "Senior Developer"
    assert data["location"] == "Remote"
    assert data["required_skills"] == []
    assert data["salary_min"] is None
    assert data["salary_max"] is None
    assert data["experience_required"] == 0
    assert data["recruiter_id"] == 11
    assert data["created_at"] == job["created_at"]


@pytest.mark.parametrize("role", ["candidate", "recruiter"])
@pytest.mark.parametrize("method", ["put", "delete"])
def test_job_mutations_require_owner(client, db, auth_headers, job, job_data, role, method):
    kwargs = {"headers": auth_headers(99, role)}
    if method == "put":
        kwargs["json"] = {**job_data, "title": "Unauthorized change"}
    response = getattr(client, method)(f"/jobs/{job['id']}", **kwargs)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    stored = db.get(JobDB, job["id"])
    assert stored.title == job_data["title"]
    assert stored.active is True


@pytest.mark.parametrize("actor", [(11, "recruiter"), (99, "admin")])
def test_delete_closes_job_and_preserves_applications(client, db, auth_headers, job, application, actor):
    response = client.delete(f"/jobs/{job['id']}", headers=auth_headers(*actor))
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.content == b""
    assert db.get(JobDB, job["id"]).active is False
    assert db.get(ApplicationDB, application["id"]) is not None
    assert client.get(
        f"/jobs/{job['id']}", headers=auth_headers(21, "candidate")
    ).json()["active"] is False
    assert client.get(
        "/applications/me", headers=auth_headers(21, "candidate")
    ).json() == [application]
    assert client.delete(
        f"/jobs/{job['id']}", headers=auth_headers(*actor)
    ).status_code == status.HTTP_204_NO_CONTENT


def test_admin_can_update_other_recruiters_job(client, auth_headers, job, job_data):
    response = client.put(
        f"/jobs/{job['id']}",
        json={**job_data, "title": "Admin edit"},
        headers=auth_headers(99, "admin"),
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["title"] == "Admin edit"
    assert response.json()["recruiter_id"] == job["recruiter_id"]


def test_job_filters_and_pagination(client, auth_headers, job_data):
    created = []
    for location, active in [("Remote", True), ("Remote", False), ("Hyderabad", True), ("Remote", True)]:
        response = client.post(
            "/jobs",
            json={**job_data, "location": location, "active": active},
            headers=auth_headers(),
        )
        created.append(response.json())
    headers = auth_headers(21, "candidate")
    response = client.get("/jobs", params={"location": "Remote", "active": True}, headers=headers)
    assert response.json() == [created[0], created[3]]
    assert client.get("/jobs", params={"active": False}, headers=headers).json() == [created[1]]
    assert client.get("/jobs", params={"limit": 2, "offset": 1}, headers=headers).json() == created[1:3]
    assert client.get("/jobs", params={"offset": 100}, headers=headers).json() == []
    assert client.get("/jobs", params={"location": "%"}, headers=headers).json() == []
    assert client.get("/jobs", headers=headers).json() == created


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"active": "perhaps"}])
def test_invalid_pagination_and_filter(client, auth_headers, params):
    assert client.get("/jobs", params=params, headers=auth_headers()).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "   "},
        {"description": ""},
        {"required_skills": ["   "]},
        {"required_skills": "Python,FastAPI"},
        {"experience_required": -1},
        {"salary_min": "-1"},
        {"salary_min": "90000.00", "salary_max": "80000.00"},
        {"salary_min": "12.345"},
    ],
)
def test_job_validation(client, db, auth_headers, job_data, changes):
    response = client.post("/jobs", json={**job_data, **changes}, headers=auth_headers())
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert db.scalar(select(JobDB)) is None


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_missing_job(client, auth_headers, job_data, method):
    kwargs = {"headers": auth_headers()}
    if method == "put":
        kwargs["json"] = job_data
    response = getattr(client, method)("/jobs/2147483647", **kwargs)
    assert response.status_code == status.HTTP_404_NOT_FOUND
