from datetime import date

from app.schemas.base import ORMBase, TimestampedRead


class DailyPlantRollupBase(ORMBase):
    plant_id: int
    rollup_date: date
    overall_yield_pct: float | None = None
    utilization_pct: float | None = None
    rate_efficiency_pct: float | None = None
    quality_pct: float | None = None
    plant_productivity_pct: float | None = None
    waste_cost_inr: float | None = None
    power_per_tonne_kwh: float | None = None
    grid_power_share_pct: float | None = None


class DailyPlantRollupCreate(DailyPlantRollupBase):
    pass


class DailyPlantRollupUpdate(ORMBase):
    plant_id: int | None = None
    rollup_date: date | None = None
    overall_yield_pct: float | None = None
    utilization_pct: float | None = None
    rate_efficiency_pct: float | None = None
    quality_pct: float | None = None
    plant_productivity_pct: float | None = None
    waste_cost_inr: float | None = None
    power_per_tonne_kwh: float | None = None
    grid_power_share_pct: float | None = None


class DailyPlantRollupRead(DailyPlantRollupBase, TimestampedRead):
    pass
