from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import Stage, pg_enum


class Machine(Base, TimestampMixin):
    """A single machine on the floor: a corrugator, a printer, or a bundling line.
    Each belongs to exactly one process stage."""

    __tablename__ = "machines"
    __table_args__ = (UniqueConstraint("plant_id", "machine_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    stage: Mapped[Stage] = mapped_column(pg_enum(Stage, "stage"), nullable=False)
    machine_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Job-independent machine capability, e.g. m/min for a corrugator or sheets/hr
    # for a printer. Job-specific standards live on Order.standard_speed instead,
    # since "a flat standard is not applied" across differing specifications.
    rated_speed: Mapped[float | None]
    rated_speed_unit: Mapped[str | None] = mapped_column(String(20))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    plant: Mapped["Plant"] = relationship(back_populates="machines")
    runs: Mapped[list["MachineRun"]] = relationship(back_populates="machine")
    parameter_readings: Mapped[list["ParameterReading"]] = relationship(back_populates="machine")
