from datetime import datetime

from sqlalchemy import Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ParameterSource, pg_enum


class ParameterReading(Base, TimestampMixin):
    """A single measurement of a cataloged metric for a machine at a point in time.

    Covers two kinds of data described in the spec, unified because both are just
    "value of metric X for machine Y at time Z":
      - PLC_LIVE: continuous operating parameters (roll temperature, steam pressure,
        glue gap) streamed from the PLC/HMI. These are leading indicators, not tied
        to a specific run.
      - QA_SAMPLE: periodic lab/QA sampling (warp, moisture, pin adhesion, bursting
        strength, ECT, caliper, caliper retention), tied to the run that produced
        the sampled output.
    """

    __tablename__ = "parameter_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), nullable=False)
    machine_run_id: Mapped[int | None] = mapped_column(ForeignKey("machine_runs.id"))
    metric_definition_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), nullable=False)
    source: Mapped[ParameterSource] = mapped_column(pg_enum(ParameterSource, "parameter_source"), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(nullable=False)

    machine: Mapped["Machine"] = relationship(back_populates="parameter_readings")
    machine_run: Mapped["MachineRun"] = relationship(back_populates="parameter_readings")
    metric_definition: Mapped["MetricDefinition"] = relationship()
