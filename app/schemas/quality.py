from app.schemas.base import ORMBase, TimestampedRead


class QualityRecordBase(ORMBase):
    machine_run_id: int
    good_qty: float
    reject_qty: float = 0
    unit: str


class QualityRecordCreate(QualityRecordBase):
    pass


class QualityRecordUpdate(ORMBase):
    machine_run_id: int | None = None
    good_qty: float | None = None
    reject_qty: float | None = None
    unit: str | None = None


class QualityRecordRead(QualityRecordBase, TimestampedRead):
    pass


class DefectObservationBase(ORMBase):
    quality_record_id: int
    reason_code_id: int
    quantity: float
    notes: str | None = None


class DefectObservationCreate(DefectObservationBase):
    pass


class DefectObservationUpdate(ORMBase):
    quality_record_id: int | None = None
    reason_code_id: int | None = None
    quantity: float | None = None
    notes: str | None = None


class DefectObservationRead(DefectObservationBase, TimestampedRead):
    pass
