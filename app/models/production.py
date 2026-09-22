from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import MaterialType, TimeCategory, pg_enum


class MachineRun(Base, TimestampMixin):
    """One machine working one order during one shift. This is the central fact
    table: material flows, time logs, quality, and bundling records all hang off it."""

    __tablename__ = "machine_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))

    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime | None]

    # Dry-end counter reading for continuous (corrugator) runs, in metres. Drives
    # average running speed / rate efficiency; left null for batch (printing) and
    # manual (bundling) stages, which measure throughput in sheets/bundles instead.
    lineal_metres: Mapped[float | None] = mapped_column(Float)

    machine: Mapped["Machine"] = relationship(back_populates="runs")
    shift: Mapped["Shift"] = relationship(back_populates="runs")
    order: Mapped["Order"] = relationship(back_populates="runs")
    material_flows: Mapped[list["MaterialFlow"]] = relationship(back_populates="machine_run")
    time_logs: Mapped[list["TimeLog"]] = relationship(back_populates="machine_run")
    quality_record: Mapped["QualityRecord"] = relationship(back_populates="machine_run", uselist=False)
    parameter_readings: Mapped[list["ParameterReading"]] = relationship(back_populates="machine_run")
    bundling_record: Mapped["BundlingRecord"] = relationship(back_populates="machine_run", uselist=False)


class MaterialFlow(Base, TimestampMixin):
    """Mass balance for a run: input vs output of a given material. The
    difference is waste attributable to that specific stage."""

    __tablename__ = "material_flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_run_id: Mapped[int] = mapped_column(ForeignKey("machine_runs.id"), nullable=False)
    material_type: Mapped[MaterialType] = mapped_column(pg_enum(MaterialType, "material_type"), nullable=False)
    input_qty: Mapped[float] = mapped_column(Float, nullable=False)
    output_qty: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "kg", "m2"

    machine_run: Mapped["MachineRun"] = relationship(back_populates="material_flows")


class TimeLog(Base, TimestampMixin):
    """One classified interval within a run: every shift-minute is running,
    setup, breakdown, waiting, or idle."""

    __tablename__ = "time_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_run_id: Mapped[int] = mapped_column(ForeignKey("machine_runs.id"), nullable=False)
    category: Mapped[TimeCategory] = mapped_column(pg_enum(TimeCategory, "time_category"), nullable=False)
    reason_code_id: Mapped[int | None] = mapped_column(ForeignKey("downtime_reason_codes.id"))
    start_time: Mapped[datetime] = mapped_column(nullable=False)
    end_time: Mapped[datetime] = mapped_column(nullable=False)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False)

    machine_run: Mapped["MachineRun"] = relationship(back_populates="time_logs")
    reason_code: Mapped["DowntimeReasonCode"] = relationship(back_populates="time_logs")
