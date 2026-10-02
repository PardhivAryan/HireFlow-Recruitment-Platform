from unittest.mock import call

from fastapi import status
import httpx
import pytest

from app.config import settings
from app.models import ApplicationDB, ApplicationStatus


@pytest.mark.parametrize("actor", [(11, "recruiter"), (99, "admin")])
def test_shortlist_calls_interview_with_database_ids(client, db, auth_headers, application, interview_post, actor):
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": "SHORTLISTED", "candidate_id": 999, "recruiter_id": 999},
        headers=auth_headers(*actor),
    )
    assert response.status_code == status.HTTP_200_OK
    assert db.get(ApplicationDB, application["id"]).status == ApplicationStatus.SHORTLISTED
    assert interview_post.call_args == call(
        f"{str(settings.interview_service_url).rstrip('/')}/internal/interviews",
        json={"application_id": application["id"], "candidate_id": 21, "recruiter_id": 11},
        headers={"X-Internal-Service-Secret": settings.internal_service_secret.get_secret_value()},
        timeout=5.0,
        follow_redirects=False,
    )


@pytest.mark.parametrize("new_status", ["APPLIED", "UNDER_REVIEW", "REJECTED"])
def test_other_statuses_do_not_call_interview(client, auth_headers, application, interview_post, new_status):
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": new_status}, headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_200_OK
    interview_post.assert_not_called()


@pytest.mark.parametrize("actor", [(21, "candidate"), (12, "recruiter")])
def test_unauthorized_shortlist_never_calls_interview(client, auth_headers, application, interview_post, actor):
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": "SHORTLISTED"}, headers=auth_headers(*actor),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    interview_post.assert_not_called()


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError, httpx.RemoteProtocolError])
def test_transport_failure_returns_503_without_status_change(client, db, auth_headers, application, interview_post, error):
    stored = db.get(ApplicationDB, application["id"])
    stored.status = ApplicationStatus.UNDER_REVIEW
    db.commit()
    interview_post.side_effect = error("downstream failure")
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": "SHORTLISTED"}, headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    db.expire_all()
    assert db.get(ApplicationDB, application["id"]).status == ApplicationStatus.UNDER_REVIEW
    assert settings.internal_service_secret.get_secret_value() not in response.text


@pytest.mark.parametrize("downstream_status", [301, 204, 400, 401, 403, 404, 409, 422, 429, 500, 503])
def test_unexpected_status_including_bad_secret_returns_503(client, db, auth_headers, application, interview_post, downstream_status):
    interview_post.side_effect = None
    interview_post.return_value = httpx.Response(downstream_status, json={"detail": "Rejected"})
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": "SHORTLISTED"}, headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    db.expire_all()
    assert db.get(ApplicationDB, application["id"]).status == ApplicationStatus.APPLIED


@pytest.mark.parametrize("kind", ["not-json", "missing-id", "wrong-application", "wrong-candidate", "wrong-recruiter"])
def test_invalid_success_response_does_not_shortlist(client, db, auth_headers, application, interview_post, kind):
    payload = {"id": 1, "application_id": application["id"], "candidate_id": 21, "recruiter_id": 11}
    if kind == "missing-id":
        del payload["id"]
    elif kind == "wrong-application":
        payload["application_id"] = 999
    elif kind == "wrong-candidate":
        payload["candidate_id"] = 999
    elif kind == "wrong-recruiter":
        payload["recruiter_id"] = 999
    interview_post.side_effect = None
    interview_post.return_value = (
        httpx.Response(200, text="not JSON") if kind == "not-json" else httpx.Response(200, json=payload)
    )
    response = client.patch(
        f"/applications/{application['id']}/status",
        json={"status": "SHORTLISTED"}, headers=auth_headers(),
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert db.get(ApplicationDB, application["id"]).status == ApplicationStatus.APPLIED


def test_retry_accepts_existing_interview_after_timeout(client, auth_headers, application, interview_post):
    interview_post.side_effect = [
        httpx.ReadTimeout("Response lost after remote creation"),
        httpx.Response(200, json={"id": 1, "application_id": application["id"], "candidate_id": 21, "recruiter_id": 11}),
    ]
    first = client.patch(
        f"/applications/{application['id']}/status", json={"status": "SHORTLISTED"}, headers=auth_headers()
    )
    second = client.patch(
        f"/applications/{application['id']}/status", json={"status": "SHORTLISTED"}, headers=auth_headers()
    )
    assert first.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert second.status_code == status.HTTP_200_OK
    assert second.json()["status"] == "SHORTLISTED"


def test_repeated_shortlist_uses_same_application_id(client, auth_headers, application, interview_post):
    for _ in range(2):
        response = client.patch(
            f"/applications/{application['id']}/status",
            json={"status": "SHORTLISTED"}, headers=auth_headers(),
        )
        assert response.status_code == status.HTTP_200_OK
    assert interview_post.call_count == 2
    assert interview_post.call_args_list[0] == interview_post.call_args_list[1]
