from datetime import date

from sqlalchemy import Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class DailyPlantRollup(Base, TimestampMixin):
    """The four plant-level headline numbers, computed daily from the underlying
    fact tables:
      - overall_yield_pct = good output dispatched / paper consumed
      - plant_productivity_pct = utilization_pct * rate_efficiency_pct * quality_pct
      - waste_cost_inr = waste kg * paper rate + starch + power share
      - power_per_tonne_kwh, with grid/DG split

    Stored rather than computed on the fly so historical trends remain stable
    even as reason-code catalogs or targets evolve later.
    """

    __tablename__ = "daily_plant_rollups"
    __table_args__ = (UniqueConstraint("plant_id", "rollup_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    rollup_date: Mapped[date] = mapped_column(nullable=False)

    overall_yield_pct: Mapped[float | None] = mapped_column(Float)

    utilization_pct: Mapped[float | None] = mapped_column(Float)
    rate_efficiency_pct: Mapped[float | None] = mapped_column(Float)
    quality_pct: Mapped[float | None] = mapped_column(Float)
    plant_productivity_pct: Mapped[float | None] = mapped_column(Float)

    waste_cost_inr: Mapped[float | None] = mapped_column(Float)

    power_per_tonne_kwh: Mapped[float | None] = mapped_column(Float)
    grid_power_share_pct: Mapped[float | None] = mapped_column(Float)

    plant: Mapped["Plant"] = relationship(back_populates="daily_rollups")
