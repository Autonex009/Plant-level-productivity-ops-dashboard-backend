from datetime import datetime

from app.models.enums import ParameterSource
from app.schemas.base import ORMBase, TimestampedRead


class ParameterReadingBase(ORMBase):
    machine_id: int
    machine_run_id: int | None = None
    metric_definition_id: int
    source: ParameterSource
    value: float
    recorded_at: datetime


class ParameterReadingCreate(ParameterReadingBase):
    pass


class ParameterReadingUpdate(ORMBase):
    machine_id: int | None = None
    machine_run_id: int | None = None
    metric_definition_id: int | None = None
    source: ParameterSource | None = None
    value: float | None = None
    recorded_at: datetime | None = None


class ParameterReadingRead(ParameterReadingBase, TimestampedRead):
    pass
