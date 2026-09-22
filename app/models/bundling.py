from sqlalchemy import Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class BundlingRecord(Base, TimestampMixin):
    """Bundling-specific measures for a run: manpower-heavy, so labour productivity
    is the honest measure, plus count accuracy and upstream starvation time."""

    __tablename__ = "bundling_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_run_id: Mapped[int] = mapped_column(ForeignKey("machine_runs.id"), unique=True, nullable=False)

    worker_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bundles_count: Mapped[int] = mapped_column(Integer, nullable=False)
    output_kg: Mapped[float | None] = mapped_column(Float)

    count_accuracy_pct: Mapped[float | None] = mapped_column(Float)  # from random audits

    # Minutes bundling stood idle awaiting material from printing. Recorded here
    # but attributable to upstream (printing) performance.
    starvation_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    machine_run: Mapped["MachineRun"] = relationship(back_populates="bundling_record")
