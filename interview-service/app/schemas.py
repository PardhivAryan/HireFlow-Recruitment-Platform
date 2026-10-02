from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl

from app.models import InterviewStatus, InterviewType


class InterviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: int = Field(gt=0, le=2_147_483_647)
    candidate_id: int = Field(gt=0, le=2_147_483_647)
    recruiter_id: int = Field(gt=0, le=2_147_483_647)


class InterviewStatusUpdate(BaseModel):
    status: InterviewStatus
    scheduled_at: AwareDatetime | None = None
    interview_type: InterviewType = InterviewType.VIDEO
    meeting_link: HttpUrl | None = Field(default=None, max_length=2048)


class InterviewFeedback(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    feedback: str = Field(min_length=1, max_length=10000)


class InterviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    candidate_id: int
    recruiter_id: int
    scheduled_at: datetime | None
    interview_type: InterviewType
    meeting_link: str | None
    status: InterviewStatus
    feedback: str | None
    created_at: datetime
