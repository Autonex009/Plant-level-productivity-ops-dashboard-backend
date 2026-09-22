from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.crud_router import build_crud_router
from app.core.database import get_db
from app.models import MetricDefinition, PlantMetricTarget
from app.models.enums import MetricCategory, Stage
from app.schemas.metrics import (
    MetricDefinitionCreate,
    MetricDefinitionRead,
    MetricDefinitionUpdate,
    PlantMetricTargetCreate,
    PlantMetricTargetRead,
    PlantMetricTargetUpdate,
)

metric_definitions_router = build_crud_router(
    model=MetricDefinition,
    create_schema=MetricDefinitionCreate,
    update_schema=MetricDefinitionUpdate,
    read_schema=MetricDefinitionRead,
    prefix="/metric-definitions",
    tags=["metric-definitions"],
)


@metric_definitions_router.get("", response_model=list[MetricDefinitionRead])
def list_metric_definitions(
    stage: Stage | None = None,
    category: MetricCategory | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[MetricDefinition]:
    query = db.query(MetricDefinition)
    if stage is not None:
        query = query.filter(MetricDefinition.stage == stage)
    if category is not None:
        query = query.filter(MetricDefinition.category == category)
    return query.offset(skip).limit(limit).all()


plant_metric_targets_router = build_crud_router(
    model=PlantMetricTarget,
    create_schema=PlantMetricTargetCreate,
    update_schema=PlantMetricTargetUpdate,
    read_schema=PlantMetricTargetRead,
    prefix="/plant-metric-targets",
    tags=["plant-metric-targets"],
)


@plant_metric_targets_router.get("", response_model=list[PlantMetricTargetRead])
def list_plant_metric_targets(
    plant_id: int | None = None,
    metric_definition_id: int | None = None,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[PlantMetricTarget]:
    query = db.query(PlantMetricTarget)
    if plant_id is not None:
        query = query.filter(PlantMetricTarget.plant_id == plant_id)
    if metric_definition_id is not None:
        query = query.filter(PlantMetricTarget.metric_definition_id == metric_definition_id)
    return query.offset(skip).limit(limit).all()
