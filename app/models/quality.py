from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class QualityRecord(Base, TimestampMixin):
    """First-pass good result for a run: good_qty / total_qty. One per run."""

    __tablename__ = "quality_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_run_id: Mapped[int] = mapped_column(ForeignKey("machine_runs.id"), unique=True, nullable=False)
    good_qty: Mapped[float] = mapped_column(Float, nullable=False)
    reject_qty: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "sheets", "kg", "bundles"

    machine_run: Mapped["MachineRun"] = relationship(back_populates="quality_record")
    defect_observations: Mapped[list["DefectObservation"]] = relationship(back_populates="quality_record")


class DefectObservation(Base, TimestampMixin):
    """Rejected quantity attributed to a specific cause, enabling Pareto analysis.
    A single run's rejects can span multiple causes."""

    __tablename__ = "defect_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    quality_record_id: Mapped[int] = mapped_column(ForeignKey("quality_records.id"), nullable=False)
    reason_code_id: Mapped[int] = mapped_column(ForeignKey("defect_reason_codes.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))

    quality_record: Mapped["QualityRecord"] = relationship(back_populates="defect_observations")
    reason_code: Mapped["DefectReasonCode"] = relationship(back_populates="defect_observations")
