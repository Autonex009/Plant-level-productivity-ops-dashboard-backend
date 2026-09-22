from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import LineType, pg_enum


class Plant(Base, TimestampMixin):
    """A physical corrugation plant. Most deployments will have exactly one row here,
    but the model supports multiple plants under one dashboard."""

    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    line_type: Mapped[LineType] = mapped_column(pg_enum(LineType, "line_type"), nullable=False)

    machines: Mapped[list["Machine"]] = relationship(back_populates="plant")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="plant")
    orders: Mapped[list["Order"]] = relationship(back_populates="plant")
    metric_targets: Mapped[list["PlantMetricTarget"]] = relationship(back_populates="plant")
    power_readings: Mapped[list["PowerReading"]] = relationship(back_populates="plant")
    daily_rollups: Mapped[list["DailyPlantRollup"]] = relationship(back_populates="plant")
