from datetime import datetime

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import ParameterReading
from app.models.enums import ParameterSource
from app.schemas.parameters import ParameterReadingCreate, ParameterReadingRead, ParameterReadingUpdate

router = build_crud_router(
    model=ParameterReading,
    create_schema=ParameterReadingCreate,
    update_schema=ParameterReadingUpdate,
    read_schema=ParameterReadingRead,
    prefix="/parameter-readings",
    tags=["parameter-readings"],
)


@router.get("", response_model=list[ParameterReadingRead])
def list_parameter_readings(
    machine_id: int | None = None,
    machine_run_id: int | None = None,
    metric_definition_id: int | None = None,
    source: ParameterSource | None = None,
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[ParameterReading]:
    query = db.query(ParameterReading)
    if machine_id is not None:
        query = query.filter(ParameterReading.machine_id == machine_id)
    if machine_run_id is not None:
        query = query.filter(ParameterReading.machine_run_id == machine_run_id)
    if metric_definition_id is not None:
        query = query.filter(ParameterReading.metric_definition_id == metric_definition_id)
    if source is not None:
        query = query.filter(ParameterReading.source == source)
    if recorded_from is not None:
        query = query.filter(ParameterReading.recorded_at >= recorded_from)
    if recorded_to is not None:
        query = query.filter(ParameterReading.recorded_at <= recorded_to)
    return query.order_by(ParameterReading.recorded_at).offset(skip).limit(limit).all()
