from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import Base, DbSession, engine
from app.dependencies import CandidateUser, CurrentUser, RecruiterOrAdmin, Role
from app.interview_client import create_interview_for_application
from app.models import ApplicationDB, ApplicationStatus, JobDB
from app.schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationStatusUpdate,
    JobCreate,
    JobResponse,
    JobUpdate,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="HireFlow Recruitment Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "recruitment-service", "status": "healthy"}


@app.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(data: JobCreate, db: DbSession, user: RecruiterOrAdmin):
    job = JobDB(**data.model_dump(), recruiter_id=user.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@app.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    db: DbSession,
    user: CurrentUser,
    location: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
):
    statement = select(JobDB)
    if location is not None:
        statement = statement.where(JobDB.location == location.strip())
    if active is not None:
        statement = statement.where(JobDB.active == active)
    statement = statement.order_by(JobDB.id).limit(limit).offset(offset)
    return db.scalars(statement).all()


@app.get("/jobs/{job_id}", response_model=JobResponse)
def read_job(
    job_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    db: DbSession,
    user: CurrentUser,
):
    job = db.get(JobDB, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@app.put("/jobs/{job_id}", response_model=JobResponse)
def update_job(
    job_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    data: JobUpdate,
    db: DbSession,
    user: RecruiterOrAdmin,
):
    job = db.get(JobDB, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if user.role != Role.admin and job.recruiter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this job")
    for field, value in data.model_dump().items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)
    return job


@app.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(
    job_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    db: DbSession,
    user: RecruiterOrAdmin,
):
    job = db.get(JobDB, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if user.role != Role.admin and job.recruiter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this job")
    # Closing a job preserves its row and its application history.
    job.active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/jobs/{job_id}/apply",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_to_job(
    job_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    db: DbSession,
    user: CandidateUser,
    data: ApplicationCreate | None = None,
):
    job = db.get(JobDB, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if not job.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is not accepting applications")
    existing = db.scalar(
        select(ApplicationDB).where(
            ApplicationDB.job_id == job_id, ApplicationDB.candidate_id == user.id
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You have already applied to this job")
    application = ApplicationDB(
        job_id=job_id,
        candidate_id=user.id,
        status=ApplicationStatus.APPLIED,
        cover_note=data.cover_note if data is not None else None,
    )
    db.add(application)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # The unique constraint also prevents simultaneous duplicate applications.
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already applied to this job",
            ) from None
        raise
    db.refresh(application)
    return application


@app.get("/applications/me", response_model=list[ApplicationResponse])
def list_my_applications(db: DbSession, user: CandidateUser):
    statement = (
        select(ApplicationDB)
        .where(ApplicationDB.candidate_id == user.id)
        .order_by(ApplicationDB.id)
    )
    return db.scalars(statement).all()


@app.get("/jobs/{job_id}/applications", response_model=list[ApplicationResponse])
def list_job_applications(
    job_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    db: DbSession,
    user: RecruiterOrAdmin,
):
    job = db.get(JobDB, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if user.role != Role.admin and job.recruiter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this job")
    statement = select(ApplicationDB).where(ApplicationDB.job_id == job_id).order_by(ApplicationDB.id)
    return db.scalars(statement).all()


@app.patch("/applications/{application_id}/status", response_model=ApplicationResponse)
def update_application_status(
    application_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    data: ApplicationStatusUpdate,
    db: DbSession,
    user: RecruiterOrAdmin,
):
    application = db.get(ApplicationDB, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    job = db.get(JobDB, application.job_id)
    if user.role != Role.admin and job.recruiter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this job")
    if data.status == ApplicationStatus.SHORTLISTED:
        # Do not save SHORTLISTED until Interview confirms creation (or an existing record).
        create_interview_for_application(application.id, application.candidate_id, job.recruiter_id)
    application.status = data.status
    db.commit()
    db.refresh(application)
    return application
