from datetime import datetime

from fastapi import status
import pytest

from app.models import InterviewDB


@pytest.mark.parametrize("actor", [(21, "candidate"), (11, "recruiter"), (99, "admin")])
def test_participants_and_admin_can_read_interview(client, auth_headers, interview, actor):
    response = client.get(f"/interviews/{interview['id']}", headers=auth_headers(*actor))
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == interview


@pytest.mark.parametrize("actor", [(22, "candidate"), (12, "recruiter")])
def test_other_users_cannot_read_interview(client, auth_headers, interview, actor):
    response = client.get(f"/interviews/{interview['id']}", headers=auth_headers(*actor))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_lists_are_scoped_to_current_user(client, auth_headers, internal_headers, interview):
    second = client.post(
        "/internal/interviews",
        json={"application_id": 102, "candidate_id": 22, "recruiter_id": 12},
        headers=internal_headers,
    ).json()
    for actor in [(21, "candidate"), (11, "recruiter")]:
        assert client.get("/interviews", headers=auth_headers(*actor)).json() == [interview]
    for actor in [(22, "candidate"), (12, "recruiter")]:
        assert client.get("/interviews", headers=auth_headers(*actor)).json() == [second]
    assert client.get("/interviews", headers=auth_headers(23, "candidate")).json() == []
    assert client.get("/interviews", headers=auth_headers(13, "recruiter")).json() == []
    assert client.get("/interviews", headers=auth_headers(99, "admin")).json() == [interview, second]
    assert client.get(
        "/interviews?candidate_id=22&recruiter_id=12", headers=auth_headers(21, "candidate")
    ).json() == [interview]


@pytest.mark.parametrize("actor", [(11, "recruiter"), (99, "admin")])
def test_recruiter_and_admin_can_schedule(client, db, auth_headers, interview, actor):
    response = client.patch(
        f"/interviews/{interview['id']}/status",
        json={
            "status": "SCHEDULED",
            "scheduled_at": "2030-01-02T15:00:00+05:30",
            "interview_type": "VIDEO",
            "meeting_link": "https://example.com/meeting",
            "candidate_id": 999,
            "recruiter_id": 999,
            "application_id": 999,
        },
        headers=auth_headers(*actor),
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "SCHEDULED"
    assert data["candidate_id"] == interview["candidate_id"]
    assert data["recruiter_id"] == interview["recruiter_id"]
    assert data["application_id"] == interview["application_id"]
    assert datetime.fromisoformat(data["scheduled_at"]) == datetime.fromisoformat("2030-01-02T09:30:00+00:00")
    assert db.get(InterviewDB, interview["id"]).meeting_link == "https://example.com/meeting"


@pytest.mark.parametrize("new_status", ["PENDING", "COMPLETED", "CANCELLED"])
def test_status_update_preserves_schedule(client, auth_headers, interview, new_status):
    scheduled = client.patch(
        f"/interviews/{interview['id']}/status",
        json={"status": "SCHEDULED", "scheduled_at": "2030-01-02T12:00:00Z", "interview_type": "PHONE"},
        headers=auth_headers(),
    ).json()
    response = client.patch(
        f"/interviews/{interview['id']}/status",
        json={"status": new_status},
        headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {**scheduled, "status": new_status}


@pytest.mark.parametrize("actor", [(21, "candidate"), (22, "candidate"), (12, "recruiter")])
def test_only_assigned_recruiter_can_manage(client, db, auth_headers, interview, actor):
    headers = auth_headers(*actor)
    changed = client.patch(
        f"/interviews/{interview['id']}/status", json={"status": "CANCELLED"}, headers=headers
    )
    feedback = client.post(
        f"/interviews/{interview['id']}/feedback", json={"feedback": "Unauthorized"}, headers=headers
    )
    assert changed.status_code == status.HTTP_403_FORBIDDEN
    assert feedback.status_code == status.HTTP_403_FORBIDDEN
    stored = db.get(InterviewDB, interview["id"])
    assert stored.status.value == "PENDING"
    assert stored.feedback is None


@pytest.mark.parametrize("actor", [(11, "recruiter"), (99, "admin")])
def test_feedback_submission(client, auth_headers, interview, actor):
    response = client.post(
        f"/interviews/{interview['id']}/feedback",
        json={"feedback": " Strong Python skills. ", "status": "COMPLETED", "candidate_id": 999},
        headers=auth_headers(*actor),
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {**interview, "feedback": "Strong Python skills."}
    updated = client.post(
        f"/interviews/{interview['id']}/feedback",
        json={"feedback": "Updated feedback"},
        headers=auth_headers(*actor),
    )
    assert updated.json()["feedback"] == "Updated feedback"
    assert client.get(
        f"/interviews/{interview['id']}", headers=auth_headers(21, "candidate")
    ).json()["feedback"] == "Updated feedback"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "UNKNOWN"},
        {"status": "SCHEDULED"},
        {"status": "SCHEDULED", "scheduled_at": "2030-01-02T12:00:00"},
        {"status": "PENDING", "meeting_link": "javascript:alert(1)"},
        {"status": "PENDING", "interview_type": None},
    ],
)
def test_invalid_status_updates(client, auth_headers, interview, body):
    response = client.patch(
        f"/interviews/{interview['id']}/status", json=body, headers=auth_headers()
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert client.get(f"/interviews/{interview['id']}", headers=auth_headers()).json() == interview


@pytest.mark.parametrize("feedback", ["   ", "x" * 10001])
def test_invalid_feedback(client, auth_headers, interview, feedback):
    response = client.post(
        f"/interviews/{interview['id']}/feedback",
        json={"feedback": feedback}, headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [("get", "", None), ("patch", "/status", {"status": "CANCELLED"}), ("post", "/feedback", {"feedback": "Notes"})],
)
def test_missing_interview(client, auth_headers, method, suffix, body):
    response = client.request(method, f"/interviews/2147483647{suffix}", json=body, headers=auth_headers())
    assert response.status_code == status.HTTP_404_NOT_FOUND
