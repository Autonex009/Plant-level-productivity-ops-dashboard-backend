from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import BundlingRecord
from app.schemas.bundling import BundlingRecordCreate, BundlingRecordRead, BundlingRecordUpdate

router = build_crud_router(
    model=BundlingRecord,
    create_schema=BundlingRecordCreate,
    update_schema=BundlingRecordUpdate,
    read_schema=BundlingRecordRead,
    prefix="/bundling-records",
    tags=["bundling-records"],
)


@router.get("", response_model=list[BundlingRecordRead])
def list_bundling_records(
    machine_run_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[BundlingRecord]:
    query = db.query(BundlingRecord)
    if machine_run_id is not None:
        query = query.filter(BundlingRecord.machine_run_id == machine_run_id)
    return query.offset(skip).limit(limit).all()
