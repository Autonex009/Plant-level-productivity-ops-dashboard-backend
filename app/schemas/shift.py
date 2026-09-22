from datetime import date, datetime

from app.schemas.base import ORMBase, TimestampedRead


class ShiftBase(ORMBase):
    plant_id: int
    shift_date: date
    shift_number: int
    start_time: datetime
    end_time: datetime
    scheduled_minutes: int


class ShiftCreate(ShiftBase):
    pass


class ShiftUpdate(ORMBase):
    plant_id: int | None = None
    shift_date: date | None = None
    shift_number: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    scheduled_minutes: int | None = None


class ShiftRead(ShiftBase, TimestampedRead):
    pass
