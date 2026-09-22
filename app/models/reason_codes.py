from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import Stage, TimeCategory, pg_enum


class DowntimeReasonCode(Base, TimestampMixin):
    """Reason catalog for non-running time (setup, breakdown, waiting, idle)."""

    __tablename__ = "downtime_reason_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[TimeCategory] = mapped_column(pg_enum(TimeCategory, "time_category"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    time_logs: Mapped[list["TimeLog"]] = relationship(back_populates="reason_code")


class DefectReasonCode(Base, TimestampMixin):
    """Reason catalog for rejected/defective output, enabling Pareto analysis by cause."""

    __tablename__ = "defect_reason_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[Stage] = mapped_column(pg_enum(Stage, "stage"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    defect_observations: Mapped[list["DefectObservation"]] = relationship(back_populates="reason_code")
