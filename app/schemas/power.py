from datetime import datetime

from app.models.enums import PowerSource
from app.schemas.base import ORMBase, TimestampedRead


class PowerReadingBase(ORMBase):
    plant_id: int
    source: PowerSource
    kwh: float
    recorded_at: datetime


class PowerReadingCreate(PowerReadingBase):
    pass


class PowerReadingUpdate(ORMBase):
    plant_id: int | None = None
    source: PowerSource | None = None
    kwh: float | None = None
    recorded_at: datetime | None = None


class PowerReadingRead(PowerReadingBase, TimestampedRead):
    pass
