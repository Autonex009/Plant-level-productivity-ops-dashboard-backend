from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import MachineRun, MaterialFlow, TimeLog
from app.models.enums import MaterialType, TimeCategory
from app.schemas.production import (
    MachineRunCreate,
    MachineRunRead,
    MachineRunUpdate,
    MaterialFlowCreate,
    MaterialFlowRead,
    MaterialFlowUpdate,
    TimeLogCreate,
    TimeLogRead,
    TimeLogUpdate,
)

machine_runs_router = build_crud_router(
    model=MachineRun,
    create_schema=MachineRunCreate,
    update_schema=MachineRunUpdate,
    read_schema=MachineRunRead,
    prefix="/machine-runs",
    tags=["machine-runs"],
)


@machine_runs_router.get("", response_model=list[MachineRunRead])
def list_machine_runs(
    machine_id: int | None = None,
    shift_id: int | None = None,
    order_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[MachineRun]:
    query = db.query(MachineRun)
    if machine_id is not None:
        query = query.filter(MachineRun.machine_id == machine_id)
    if shift_id is not None:
        query = query.filter(MachineRun.shift_id == shift_id)
    if order_id is not None:
        query = query.filter(MachineRun.order_id == order_id)
    return query.offset(skip).limit(limit).all()


material_flows_router = build_crud_router(
    model=MaterialFlow,
    create_schema=MaterialFlowCreate,
    update_schema=MaterialFlowUpdate,
    read_schema=MaterialFlowRead,
    prefix="/material-flows",
    tags=["material-flows"],
)


@material_flows_router.get("", response_model=list[MaterialFlowRead])
def list_material_flows(
    machine_run_id: int | None = None,
    material_type: MaterialType | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[MaterialFlow]:
    query = db.query(MaterialFlow)
    if machine_run_id is not None:
        query = query.filter(MaterialFlow.machine_run_id == machine_run_id)
    if material_type is not None:
        query = query.filter(MaterialFlow.material_type == material_type)
    return query.offset(skip).limit(limit).all()


time_logs_router = build_crud_router(
    model=TimeLog,
    create_schema=TimeLogCreate,
    update_schema=TimeLogUpdate,
    read_schema=TimeLogRead,
    prefix="/time-logs",
    tags=["time-logs"],
)


@time_logs_router.get("", response_model=list[TimeLogRead])
def list_time_logs(
    machine_run_id: int | None = None,
    category: TimeCategory | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[TimeLog]:
    query = db.query(TimeLog)
    if machine_run_id is not None:
        query = query.filter(TimeLog.machine_run_id == machine_run_id)
    if category is not None:
        query = query.filter(TimeLog.category == category)
    return query.offset(skip).limit(limit).all()
