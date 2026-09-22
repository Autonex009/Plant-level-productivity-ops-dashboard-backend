from datetime import datetime

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import PowerReading
from app.models.enums import PowerSource
from app.schemas.power import PowerReadingCreate, PowerReadingRead, PowerReadingUpdate

router = build_crud_router(
    model=PowerReading,
    create_schema=PowerReadingCreate,
    update_schema=PowerReadingUpdate,
    read_schema=PowerReadingRead,
    prefix="/power-readings",
    tags=["power-readings"],
)


@router.get("", response_model=list[PowerReadingRead])
def list_power_readings(
    plant_id: int | None = None,
    source: PowerSource | None = None,
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[PowerReading]:
    query = db.query(PowerReading)
    if plant_id is not None:
        query = query.filter(PowerReading.plant_id == plant_id)
    if source is not None:
        query = query.filter(PowerReading.source == source)
    if recorded_from is not None:
        query = query.filter(PowerReading.recorded_at >= recorded_from)
    if recorded_to is not None:
        query = query.filter(PowerReading.recorded_at <= recorded_to)
    return query.order_by(PowerReading.recorded_at).offset(skip).limit(limit).all()
