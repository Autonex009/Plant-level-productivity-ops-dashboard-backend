from datetime import datetime

from app.models.enums import MaterialType, TimeCategory
from app.schemas.base import ORMBase, TimestampedRead


class MachineRunBase(ORMBase):
    machine_id: int
    shift_id: int
    order_id: int | None = None
    start_time: datetime
    end_time: datetime | None = None
    lineal_metres: float | None = None


class MachineRunCreate(MachineRunBase):
    pass


class MachineRunUpdate(ORMBase):
    machine_id: int | None = None
    shift_id: int | None = None
    order_id: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    lineal_metres: float | None = None


class MachineRunRead(MachineRunBase, TimestampedRead):
    pass


class MaterialFlowBase(ORMBase):
    machine_run_id: int
    material_type: MaterialType
    input_qty: float
    output_qty: float | None = None
    unit: str


class MaterialFlowCreate(MaterialFlowBase):
    pass


class MaterialFlowUpdate(ORMBase):
    machine_run_id: int | None = None
    material_type: MaterialType | None = None
    input_qty: float | None = None
    output_qty: float | None = None
    unit: str | None = None


class MaterialFlowRead(MaterialFlowBase, TimestampedRead):
    pass


class TimeLogBase(ORMBase):
    machine_run_id: int
    category: TimeCategory
    reason_code_id: int | None = None
    start_time: datetime
    end_time: datetime
    duration_minutes: float


class TimeLogCreate(TimeLogBase):
    pass


class TimeLogUpdate(ORMBase):
    machine_run_id: int | None = None
    category: TimeCategory | None = None
    reason_code_id: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_minutes: float | None = None


class TimeLogRead(TimeLogBase, TimestampedRead):
    pass
