from datetime import date

from pydantic import computed_field

from app.models.enums import MetricCategory, Stage
from app.schemas.base import ORMBase, TimestampedRead


class MetricDefinitionBase(ORMBase):
    code: str
    name: str
    definition: str
    unit: str
    category: MetricCategory
    stage: Stage | None = None


class MetricDefinitionCreate(MetricDefinitionBase):
    pass


class MetricDefinitionUpdate(ORMBase):
    code: str | None = None
    name: str | None = None
    definition: str | None = None
    unit: str | None = None
    category: MetricCategory | None = None
    stage: Stage | None = None


class MetricDefinitionRead(MetricDefinitionBase, TimestampedRead):
    @computed_field
    @property
    def lower_is_better(self) -> bool:
        """Which way is good for this metric.

        Served rather than left for each client to work out, because the answer
        decides which side of a target is green - and a second copy of that list
        in a UI is a copy that will eventually disagree with the one the RAG
        verdicts are actually computed from.
        """
        from app.services.dashboard.bands import LOWER_IS_BETTER

        return self.code in LOWER_IS_BETTER


class PlantMetricTargetBase(ORMBase):
    plant_id: int
    metric_definition_id: int
    target_value: float
    effective_from: date
    red_line_value: float | None = None
    band_low: float | None = None
    band_high: float | None = None
    monsoon_band_low: float | None = None
    monsoon_band_high: float | None = None


class PlantMetricTargetCreate(PlantMetricTargetBase):
    pass


class PlantMetricTargetUpdate(ORMBase):
    plant_id: int | None = None
    metric_definition_id: int | None = None
    target_value: float | None = None
    effective_from: date | None = None
    red_line_value: float | None = None
    band_low: float | None = None
    band_high: float | None = None
    monsoon_band_low: float | None = None
    monsoon_band_high: float | None = None


class PlantMetricTargetRead(PlantMetricTargetBase, TimestampedRead):
    pass
