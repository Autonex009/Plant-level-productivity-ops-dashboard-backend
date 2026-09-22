from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import Stage
from app.schemas.analytics import DefectParetoEntry, MachineRunMetrics, ShiftMachineUptime
from app.services import metrics as metrics_service

router = APIRouter(tags=["analytics"])


@router.get("/machine-runs/{machine_run_id}/metrics", response_model=MachineRunMetrics)
def get_machine_run_metrics(machine_run_id: int, db: Session = Depends(get_db)) -> dict:
    return metrics_service.machine_run_metrics(db, machine_run_id)


@router.get("/shifts/{shift_id}/uptime", response_model=list[ShiftMachineUptime])
def get_shift_uptime(shift_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return metrics_service.shift_uptime_pct(db, shift_id)


@router.get("/defect-pareto", response_model=list[DefectParetoEntry])
def get_defect_pareto(
    plant_id: int | None = None,
    stage: Stage | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    return metrics_service.defect_pareto(db, plant_id=plant_id, stage=stage, date_from=date_from, date_to=date_to)
