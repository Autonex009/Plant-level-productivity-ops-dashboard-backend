from datetime import date

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
    pass


class PlantMetricTargetBase(ORMBase):
    plant_id: int
    metric_definition_id: int
    target_value: float
    effective_from: date


class PlantMetricTargetCreate(PlantMetricTargetBase):
    pass


class PlantMetricTargetUpdate(ORMBase):
    plant_id: int | None = None
    metric_definition_id: int | None = None
    target_value: float | None = None
    effective_from: date | None = None


class PlantMetricTargetRead(PlantMetricTargetBase, TimestampedRead):
    pass
