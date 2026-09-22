from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import DefectObservation, QualityRecord
from app.schemas.quality import (
    DefectObservationCreate,
    DefectObservationRead,
    DefectObservationUpdate,
    QualityRecordCreate,
    QualityRecordRead,
    QualityRecordUpdate,
)

quality_records_router = build_crud_router(
    model=QualityRecord,
    create_schema=QualityRecordCreate,
    update_schema=QualityRecordUpdate,
    read_schema=QualityRecordRead,
    prefix="/quality-records",
    tags=["quality-records"],
)


@quality_records_router.get("", response_model=list[QualityRecordRead])
def list_quality_records(
    machine_run_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[QualityRecord]:
    query = db.query(QualityRecord)
    if machine_run_id is not None:
        query = query.filter(QualityRecord.machine_run_id == machine_run_id)
    return query.offset(skip).limit(limit).all()


defect_observations_router = build_crud_router(
    model=DefectObservation,
    create_schema=DefectObservationCreate,
    update_schema=DefectObservationUpdate,
    read_schema=DefectObservationRead,
    prefix="/defect-observations",
    tags=["defect-observations"],
)


@defect_observations_router.get("", response_model=list[DefectObservationRead])
def list_defect_observations(
    quality_record_id: int | None = None,
    reason_code_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[DefectObservation]:
    query = db.query(DefectObservation)
    if quality_record_id is not None:
        query = query.filter(DefectObservation.quality_record_id == quality_record_id)
    if reason_code_id is not None:
        query = query.filter(DefectObservation.reason_code_id == reason_code_id)
    return query.offset(skip).limit(limit).all()
