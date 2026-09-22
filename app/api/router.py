from fastapi import APIRouter

from app.api.routers.analytics import router as analytics_router
from app.api.routers.bundling import router as bundling_records_router
from app.api.routers.dashboard import router as dashboard_router
from app.api.routers.machines import router as machines_router
from app.api.routers.metrics import (
    metric_definitions_router,
    plant_metric_targets_router,
)
from app.api.routers.orders import router as orders_router
from app.api.routers.parameters import router as parameter_readings_router
from app.api.routers.plants import router as plants_router
from app.api.routers.power import router as power_readings_router
from app.api.routers.production import (
    machine_runs_router,
    material_flows_router,
    time_logs_router,
)
from app.api.routers.quality import (
    defect_observations_router,
    quality_records_router,
)
from app.api.routers.reason_codes import (
    defect_reason_codes_router,
    downtime_reason_codes_router,
)
from app.api.routers.rollup import router as daily_plant_rollups_router
from app.api.routers.shifts import router as shifts_router

api_router = APIRouter()

for router in (
    plants_router,
    machines_router,
    metric_definitions_router,
    plant_metric_targets_router,
    downtime_reason_codes_router,
    defect_reason_codes_router,
    shifts_router,
    orders_router,
    machine_runs_router,
    material_flows_router,
    time_logs_router,
    quality_records_router,
    defect_observations_router,
    parameter_readings_router,
    bundling_records_router,
    power_readings_router,
    daily_plant_rollups_router,
    analytics_router,
    dashboard_router,
):
    api_router.include_router(router)
