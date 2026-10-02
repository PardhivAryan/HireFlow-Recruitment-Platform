import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings


class InterviewReceipt(BaseModel):
    id: int = Field(gt=0, strict=True)
    application_id: int = Field(gt=0, strict=True)
    candidate_id: int = Field(gt=0, strict=True)
    recruiter_id: int = Field(gt=0, strict=True)


def create_interview_for_application(
    application_id: int, candidate_id: int, recruiter_id: int
) -> None:
    unavailable = HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Interview service could not create the interview; retry the shortlist request",
    )
    payload = {
        "application_id": application_id,
        "candidate_id": candidate_id,
        "recruiter_id": recruiter_id,
    }
    try:
        response = httpx.post(
            f"{str(settings.interview_service_url).rstrip('/')}/internal/interviews",
            json=payload,
            headers={"X-Internal-Service-Secret": settings.internal_service_secret.get_secret_value()},
            timeout=5.0,
            follow_redirects=False,
        )
    except httpx.RequestError:
        # Includes timeouts, connection failures, and HTTP transport errors.
        raise unavailable from None

    if response.status_code not in (status.HTTP_200_OK, status.HTTP_201_CREATED):
        # Includes invalid internal credentials and unexpected downstream statuses.
        raise unavailable
    try:
        receipt = InterviewReceipt.model_validate(response.json())
    except ValueError:
        raise unavailable from None
    if (
        receipt.application_id != application_id
        or receipt.candidate_id != candidate_id
        or receipt.recruiter_id != recruiter_id
    ):
        raise unavailable
