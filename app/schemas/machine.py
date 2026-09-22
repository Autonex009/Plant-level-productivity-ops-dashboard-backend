from app.models.enums import Stage
from app.schemas.base import ORMBase, TimestampedRead


class MachineBase(ORMBase):
    plant_id: int
    stage: Stage
    machine_code: str
    name: str
    rated_speed: float | None = None
    rated_speed_unit: str | None = None
    is_active: bool = True


class MachineCreate(MachineBase):
    pass


class MachineUpdate(ORMBase):
    plant_id: int | None = None
    stage: Stage | None = None
    machine_code: str | None = None
    name: str | None = None
    rated_speed: float | None = None
    rated_speed_unit: str | None = None
    is_active: bool | None = None


class MachineRead(MachineBase, TimestampedRead):
    pass
