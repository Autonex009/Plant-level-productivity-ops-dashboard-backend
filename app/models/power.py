from datetime import datetime

from sqlalchemy import Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import PowerSource, pg_enum


class PowerReading(Base, TimestampMixin):
    """Power consumption by source. Grid vs DG split matters because genset
    running hours are pure margin leakage."""

    __tablename__ = "power_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    source: Mapped[PowerSource] = mapped_column(pg_enum(PowerSource, "power_source"), nullable=False)
    kwh: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(nullable=False)

    plant: Mapped["Plant"] = relationship(back_populates="power_readings")
