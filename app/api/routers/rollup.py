from datetime import date

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import DailyPlantRollup
from app.schemas.rollup import DailyPlantRollupCreate, DailyPlantRollupRead, DailyPlantRollupUpdate
from app.services import metrics as metrics_service

router = build_crud_router(
    model=DailyPlantRollup,
    create_schema=DailyPlantRollupCreate,
    update_schema=DailyPlantRollupUpdate,
    read_schema=DailyPlantRollupRead,
    prefix="/daily-plant-rollups",
    tags=["daily-plant-rollups"],
)


@router.get("", response_model=list[DailyPlantRollupRead])
def list_daily_plant_rollups(
    plant_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[DailyPlantRollup]:
    query = db.query(DailyPlantRollup)
    if plant_id is not None:
        query = query.filter(DailyPlantRollup.plant_id == plant_id)
    if date_from is not None:
        query = query.filter(DailyPlantRollup.rollup_date >= date_from)
    if date_to is not None:
        query = query.filter(DailyPlantRollup.rollup_date <= date_to)
    return query.order_by(DailyPlantRollup.rollup_date).offset(skip).limit(limit).all()


@router.post("/compute", response_model=DailyPlantRollupRead)
def compute_daily_plant_rollup(
    plant_id: int,
    rollup_date: date,
    paper_rate_per_kg: float | None = None,
    db: Session = Depends(get_db),
) -> DailyPlantRollup:
    """Recomputes overall yield, utilization, rate efficiency, quality, plant
    productivity, power/tonne, and grid share for one plant-day from the
    underlying fact tables, and upserts the DailyPlantRollup row."""
    return metrics_service.compute_daily_plant_rollup(
        db, plant_id=plant_id, rollup_date=rollup_date, paper_rate_per_kg=paper_rate_per_kg
    )
