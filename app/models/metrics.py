from datetime import date

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import MetricCategory, Stage, pg_enum


class MetricDefinition(Base, TimestampMixin):
    """Catalog entry for a single metric, as tabulated per-stage in the spec
    (category, metric, definition, unit). Stage=None marks a plant-level rollup
    metric that sits above the three stages (e.g. overall yield)."""

    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[MetricCategory] = mapped_column(pg_enum(MetricCategory, "metric_category"), nullable=False)
    stage: Mapped[Stage | None] = mapped_column(pg_enum(Stage, "stage"))

    targets: Mapped[list["PlantMetricTarget"]] = relationship(back_populates="metric_definition")


class PlantMetricTarget(Base, TimestampMixin):
    """Reference performance level for a metric, set per plant baseline. The spec
    leaves these blank until a plant establishes its own baseline, and supports
    revising them over time via effective_from.

    Carries the full RAG band, not just the target: green is at or better than
    target, amber sits between target and red_line, red is worse than red_line.
    Parameters (roll temperature, steam pressure, glue gap) are judged against a
    two-sided control band instead, with monsoon variants for the metrics the spec
    calls out as season-sensitive (moisture, warp, yield).
    """

    __tablename__ = "plant_metric_targets"
    __table_args__ = (UniqueConstraint("plant_id", "metric_definition_id", "effective_from"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    metric_definition_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    effective_from: Mapped[date] = mapped_column(nullable=False)

    # Amber/red boundary. Null means the plant has not set one yet and the
    # dashboard falls back to a derived line (see services/dashboard.resolve_band).
    red_line_value: Mapped[float | None] = mapped_column(Float)

    # Two-sided control band for operating parameters, with monsoon variants.
    band_low: Mapped[float | None] = mapped_column(Float)
    band_high: Mapped[float | None] = mapped_column(Float)
    monsoon_band_low: Mapped[float | None] = mapped_column(Float)
    monsoon_band_high: Mapped[float | None] = mapped_column(Float)

    plant: Mapped["Plant"] = relationship(back_populates="metric_targets")
    metric_definition: Mapped["MetricDefinition"] = relationship(back_populates="targets")
