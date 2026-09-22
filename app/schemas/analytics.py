from pydantic import BaseModel


class MachineRunMetrics(BaseModel):
    machine_run_id: int
    yield_pct: float | None
    quality_pct: float | None
    rate_efficiency_pct: float | None
    running_minutes: float
    bundles_per_hour: float | None
    output_per_worker_shift: float | None


class ShiftMachineUptime(BaseModel):
    machine_id: int
    running_minutes: float
    scheduled_minutes: int
    uptime_pct: float | None


class DefectParetoEntry(BaseModel):
    code: str
    description: str
    quantity: float
