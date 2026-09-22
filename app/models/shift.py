from datetime import date, datetime

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Shift(Base, TimestampMixin):
    """A single shift at a plant. Scheduled_minutes is the denominator for
    machine utilisation (running time / scheduled time)."""

    __tablename__ = "shifts"
    __table_args__ = (UniqueConstraint("plant_id", "shift_date", "shift_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    shift_date: Mapped[date] = mapped_column(nullable=False)
    shift_number: Mapped[int] = mapped_column(nullable=False)
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime] = mapped_column(nullable=False)
    scheduled_minutes: Mapped[int] = mapped_column(nullable=False)

    plant: Mapped["Plant"] = relationship(back_populates="shifts")
    runs: Mapped[list["MachineRun"]] = relationship(back_populates="shift")
