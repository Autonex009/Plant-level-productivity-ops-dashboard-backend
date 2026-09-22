from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import DefectReasonCode, DowntimeReasonCode
from app.models.enums import Stage, TimeCategory
from app.schemas.reason_codes import (
    DefectReasonCodeCreate,
    DefectReasonCodeRead,
    DefectReasonCodeUpdate,
    DowntimeReasonCodeCreate,
    DowntimeReasonCodeRead,
    DowntimeReasonCodeUpdate,
)

downtime_reason_codes_router = build_crud_router(
    model=DowntimeReasonCode,
    create_schema=DowntimeReasonCodeCreate,
    update_schema=DowntimeReasonCodeUpdate,
    read_schema=DowntimeReasonCodeRead,
    prefix="/downtime-reason-codes",
    tags=["downtime-reason-codes"],
)


@downtime_reason_codes_router.get("", response_model=list[DowntimeReasonCodeRead])
def list_downtime_reason_codes(
    category: TimeCategory | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[DowntimeReasonCode]:
    query = db.query(DowntimeReasonCode)
    if category is not None:
        query = query.filter(DowntimeReasonCode.category == category)
    return query.offset(skip).limit(limit).all()


defect_reason_codes_router = build_crud_router(
    model=DefectReasonCode,
    create_schema=DefectReasonCodeCreate,
    update_schema=DefectReasonCodeUpdate,
    read_schema=DefectReasonCodeRead,
    prefix="/defect-reason-codes",
    tags=["defect-reason-codes"],
)


@defect_reason_codes_router.get("", response_model=list[DefectReasonCodeRead])
def list_defect_reason_codes(
    stage: Stage | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[DefectReasonCode]:
    query = db.query(DefectReasonCode)
    if stage is not None:
        query = query.filter(DefectReasonCode.stage == stage)
    return query.offset(skip).limit(limit).all()
