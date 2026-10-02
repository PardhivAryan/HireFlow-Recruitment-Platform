from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ApplicationStatus


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    required_skills: list[str] = Field(default_factory=list, max_length=50)
    location: str = Field(min_length=1, max_length=200)
    experience_required: int = Field(default=0, ge=0, le=100)
    salary_min: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    salary_max: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    active: bool = True

    @field_validator("required_skills")
    @classmethod
    def validate_skills(cls, skills: list[str]) -> list[str]:
        if any(not skill or len(skill) > 100 for skill in skills):
            raise ValueError("Each skill must contain 1–100 characters")
        return skills

    @model_validator(mode="after")
    def validate_salary_range(self):
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                raise ValueError("salary_min must not exceed salary_max")
        return self


class JobUpdate(JobCreate):
    # PUT replaces the editable fields, using the same validation as creation.
    pass


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recruiter_id: int
    title: str
    description: str
    required_skills: list[str]
    location: str
    experience_required: int
    salary_min: Decimal | None
    salary_max: Decimal | None
    active: bool
    created_at: datetime


class ApplicationCreate(BaseModel):
    cover_note: str | None = Field(default=None, max_length=5000)


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    candidate_id: int
    status: ApplicationStatus
    cover_note: str | None
    applied_at: datetime
