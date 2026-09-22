from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import Machine
from app.models.enums import Stage
from app.schemas.machine import MachineCreate, MachineRead, MachineUpdate

router = build_crud_router(
    model=Machine,
    create_schema=MachineCreate,
    update_schema=MachineUpdate,
    read_schema=MachineRead,
    prefix="/machines",
    tags=["machines"],
)


@router.get("", response_model=list[MachineRead])
def list_machines(
    plant_id: int | None = None,
    stage: Stage | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[Machine]:
    query = db.query(Machine)
    if plant_id is not None:
        query = query.filter(Machine.plant_id == plant_id)
    if stage is not None:
        query = query.filter(Machine.stage == stage)
    return query.offset(skip).limit(limit).all()
