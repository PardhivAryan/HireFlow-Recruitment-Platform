from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import Base, DbSession, engine
from app.dependencies import CurrentUser, RecruiterOrAdmin, Role, require_internal_service
from app.models import InterviewDB, InterviewStatus
from app.schemas import InterviewCreate, InterviewFeedback, InterviewResponse, InterviewStatusUpdate


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="HireFlow Interview Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"service": "interview-service", "status": "healthy"}


@app.post(
    "/internal/interviews",
    response_model=InterviewResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_service)],
)
def create_internal_interview(data: InterviewCreate, db: DbSession, response: Response):
    interview = db.scalar(
        select(InterviewDB).where(InterviewDB.application_id == data.application_id)
    )
    if interview is None:
        interview = InterviewDB(**data.model_dump())
        db.add(interview)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            # A concurrent request may have created this application's interview.
            if getattr(exc.orig, "sqlstate", None) != "23505":
                raise
            interview = db.scalar(
                select(InterviewDB).where(InterviewDB.application_id == data.application_id)
            )
            if interview is None:
                raise
            response.status_code = status.HTTP_200_OK
        else:
            db.refresh(interview)
    else:
        response.status_code = status.HTTP_200_OK

    if interview.candidate_id != data.candidate_id or interview.recruiter_id != data.recruiter_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application's interview belongs to different participants",
        )
    return interview


@app.get("/interviews", response_model=list[InterviewResponse])
def list_interviews(db: DbSession, user: CurrentUser):
    statement = select(InterviewDB)
    if user.role == Role.candidate:
        statement = statement.where(InterviewDB.candidate_id == user.id)
    elif user.role == Role.recruiter:
        statement = statement.where(InterviewDB.recruiter_id == user.id)
    return db.scalars(statement.order_by(InterviewDB.id)).all()


@app.get("/interviews/{interview_id}", response_model=InterviewResponse)
def read_interview(
    interview_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    db: DbSession,
    user: CurrentUser,
):
    interview = db.get(InterviewDB, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if user.role == Role.candidate and interview.candidate_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This is not your interview")
    if user.role == Role.recruiter and interview.recruiter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This interview is not assigned to you")
    return interview


@app.patch("/interviews/{interview_id}/status", response_model=InterviewResponse)
def update_interview_status(
    interview_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    data: InterviewStatusUpdate,
    db: DbSession,
    user: RecruiterOrAdmin,
):
    interview = db.get(InterviewDB, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if user.role != Role.admin and interview.recruiter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This interview is not assigned to you")

    changes = data.model_dump(exclude_unset=True)
    scheduled_at = changes.get("scheduled_at", interview.scheduled_at)
    if data.status == InterviewStatus.SCHEDULED and scheduled_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A scheduled interview must have scheduled_at",
        )
    for field, value in changes.items():
        if field == "meeting_link" and value is not None:
            value = str(value)
        setattr(interview, field, value)
    db.commit()
    db.refresh(interview)
    return interview


@app.post("/interviews/{interview_id}/feedback", response_model=InterviewResponse)
def submit_feedback(
    interview_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    data: InterviewFeedback,
    db: DbSession,
    user: RecruiterOrAdmin,
):
    interview = db.get(InterviewDB, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    if user.role != Role.admin and interview.recruiter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This interview is not assigned to you")
    interview.feedback = data.feedback
    db.commit()
    db.refresh(interview)
    return interview
