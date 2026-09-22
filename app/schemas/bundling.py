from app.schemas.base import ORMBase, TimestampedRead


class BundlingRecordBase(ORMBase):
    machine_run_id: int
    worker_count: int
    bundles_count: int
    output_kg: float | None = None
    count_accuracy_pct: float | None = None
    starvation_minutes: float = 0


class BundlingRecordCreate(BundlingRecordBase):
    pass


class BundlingRecordUpdate(ORMBase):
    machine_run_id: int | None = None
    worker_count: int | None = None
    bundles_count: int | None = None
    output_kg: float | None = None
    count_accuracy_pct: float | None = None
    starvation_minutes: float | None = None


class BundlingRecordRead(BundlingRecordBase, TimestampedRead):
    pass
