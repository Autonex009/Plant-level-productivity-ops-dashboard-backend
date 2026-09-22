from datetime import date

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import Shift
from app.schemas.shift import ShiftCreate, ShiftRead, ShiftUpdate

router = build_crud_router(
    model=Shift,
    create_schema=ShiftCreate,
    update_schema=ShiftUpdate,
    read_schema=ShiftRead,
    prefix="/shifts",
    tags=["shifts"],
)


@router.get("", response_model=list[ShiftRead])
def list_shifts(
    plant_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[Shift]:
    query = db.query(Shift)
    if plant_id is not None:
        query = query.filter(Shift.plant_id == plant_id)
    if date_from is not None:
        query = query.filter(Shift.shift_date >= date_from)
    if date_to is not None:
        query = query.filter(Shift.shift_date <= date_to)
    return query.order_by(Shift.shift_date, Shift.shift_number).offset(skip).limit(limit).all()
