from datetime import date, datetime

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Order(Base, TimestampMixin):
    """A production job. Specification fields (ply, flute, paper grade, sheet size)
    drive the job-specific standards that machine runs are measured against, since
    "a flat standard is not applied" across differing constructions."""

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("plant_id", "order_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    order_number: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(255))

    ply_construction: Mapped[str | None] = mapped_column(String(20))  # e.g. "3-ply", "5-ply"
    flute_profile: Mapped[str | None] = mapped_column(String(10))  # e.g. "B", "BC", "E"
    sheet_length_mm: Mapped[float | None] = mapped_column(Float)
    sheet_width_mm: Mapped[float | None] = mapped_column(Float)
    paper_gsm: Mapped[float | None] = mapped_column(Float)
    paper_bf: Mapped[float | None] = mapped_column(Float)

    quantity_ordered: Mapped[int | None] = mapped_column(Integer)
    due_date: Mapped[date | None]

    # Job-specific throughput standard, since it varies by ply/flute/spec.
    # This is the corrugator's standard, in m/min: boarding is continuous.
    standard_speed: Mapped[float | None] = mapped_column(Float)
    standard_speed_unit: Mapped[str | None] = mapped_column(String(20))  # e.g. "m/min", "sheets/hr"

    # The same job's printing standard, in sheets/hr. Printing is a batch process
    # whose standard varies by colour count, size and board grade, so it cannot be
    # derived from the corrugator's metres-per-minute figure.
    printing_standard_sheets_per_hr: Mapped[float | None] = mapped_column(Float)

    # Captured at bundling: basis of on-time delivery reporting.
    order_complete_staged_at: Mapped[datetime | None]

    plant: Mapped["Plant"] = relationship(back_populates="orders")
    runs: Mapped[list["MachineRun"]] = relationship(back_populates="order")
