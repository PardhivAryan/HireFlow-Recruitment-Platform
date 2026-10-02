from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InterviewStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InterviewType(str, Enum):
    VIDEO = "VIDEO"
    PHONE = "PHONE"
    IN_PERSON = "IN_PERSON"


class InterviewDB(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(unique=True, index=True)
    candidate_id: Mapped[int] = mapped_column(index=True)
    recruiter_id: Mapped[int] = mapped_column(index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_type: Mapped[InterviewType] = mapped_column(
        SqlEnum(InterviewType, native_enum=False, create_constraint=True),
        default=InterviewType.VIDEO,
    )
    meeting_link: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[InterviewStatus] = mapped_column(
        SqlEnum(InterviewStatus, native_enum=False, create_constraint=True),
        default=InterviewStatus.PENDING,
    )
    feedback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
