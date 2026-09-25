"""The dashboard read API: one call per screen.

The CRUD routers expose the entities; this router exposes the three levels of the
dashboard itself. Keeping the composition server-side is deliberate - the alert
thresholds, the RAG bands and the comparison-fairness rule are policy, and policy
belongs next to the data rather than in a browser.

Responses are intentionally loose dicts rather than deeply-typed models: these are
read-only screen payloads that evolve with the layout, and the shapes are
documented by the service functions that build them.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Plant
from app.models.enums import Stage
from app.services.dashboard import alerts as alerts_service
from app.services.dashboard import plant as plant_service
from app.services.dashboard import specifics as specifics_service
from app.services.dashboard import stage as stage_service
from app.services.dashboard.bands import load_bands
from app.services.dashboard.ranges import RangeMode, RangeSpec, resolve_range
from app.services.dashboard.self_heal import heal_if_stale

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Level 1 shows at most five alerts. Beyond that the panel stops being a
# to-do list and becomes wallpaper.
LEVEL_1_ALERT_CAP = 5


def _require_plant(db: Session, plant_id: int) -> Plant:
    plant = db.get(Plant, plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"Plant {plant_id} not found")
    return plant


def _spec(
    range_mode: RangeMode,
    date_from: date | None,
    date_to: date | None,
    now: datetime,
) -> RangeSpec:
    try:
        return resolve_range(range_mode, today=now.date(), date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _now(as_of: datetime | None) -> datetime:
    """as_of exists so the demo data and the tests can pin "now" to a known
    instant; live callers omit it."""
    return as_of or datetime.now()


@router.get("/plants/{plant_id}/overview")
def get_plant_overview(
    plant_id: int,
    range_mode: RangeMode = Query(RangeMode.TODAY, alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Level 1 - the landing screen. Status line, four rollups, two charts, and
    the alerts panel (which becomes the recurring-issues list in aggregate modes)."""
    _require_plant(db, plant_id)
    now = _now(as_of)
    spec = _spec(range_mode, date_from, date_to, now)
    # Both of these render live machine state, so both are worth healing.
    # No-ops unless the demo flag is on and the data has actually gone stale.
    heal_if_stale(db, plant_id, now)

    overview = plant_service.plant_overview(db, plant_id, spec, now=now)
    bands = load_bands(db, plant_id, on_date=spec.end)

    live_alerts = [
        *alerts_service.event_alerts(db, plant_id, now=now),
        *alerts_service.breach_alerts(overview["rollups"]),
        *alerts_service.drift_alerts(db, plant_id, bands, now=now),
    ]
    overview["alerts"] = alerts_service.rank_and_cap(live_alerts, level=1, cap=LEVEL_1_ALERT_CAP)

    # Today runs the shift, so it shows live alerts. Week runs the review, Month
    # runs the business, and both want the recurring-issues list instead.
    overview["recurring_issues"] = (
        alerts_service.recurring_issues(db, plant_id, spec.start, spec.end)
        if spec.mode is not RangeMode.TODAY
        else []
    )
    overview["alerts_panel_mode"] = "live" if spec.mode is RangeMode.TODAY else "recurring"
    return overview


@router.get("/plants/{plant_id}/trends")
def get_plant_trends(
    plant_id: int,
    days: int = Query(30, ge=7, le=180),
    as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """30-day lines for the four rollups with target bands. Monsoon days carry a
    marker so a seasonal dip reads as expected rather than as failure."""
    _require_plant(db, plant_id)
    now = _now(as_of)
    trends = plant_service.trend_series(db, plant_id, now.date(), days=days, as_of=now)

    bands = load_bands(db, plant_id, on_date=now.date())
    trends["bands"] = {
        code: {"target": band.target, "red_line": band.red_line, "lower_is_better": band.lower_is_better}
        for code, band in bands.items()
        if code in {"overall_yield_pct", "plant_productivity_pct", "cost_of_waste_inr", "power_per_tonne_kwh"}
    }
    return trends


@router.get("/plants/{plant_id}/stages/{stage}")
def get_stage_view(
    plant_id: int,
    stage: Stage,
    range_mode: RangeMode = Query(RangeMode.TODAY, alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Level 2 - one template, three stages. Context row, five KPI cards, two
    signature charts, the stage alert panel, and a small 7-day trend."""
    _require_plant(db, plant_id)
    now = _now(as_of)
    spec = _spec(range_mode, date_from, date_to, now)
    # Both of these render live machine state, so both are worth healing.
    # No-ops unless the demo flag is on and the data has actually gone stale.
    heal_if_stale(db, plant_id, now)

    view = stage_service.stage_view(db, plant_id, stage, spec, now=now)
    bands = load_bands(db, plant_id, on_date=spec.end)

    # Drift and pattern alerts are born here. Level 1 only ever sees the ones
    # nobody acted on.
    stage_alerts = [
        *[
            alert
            for alert in alerts_service.event_alerts(db, plant_id, now=now)
            if alert.stage == stage.value
        ],
        *alerts_service.breach_alerts(view["kpis"], stage=stage, level=2),
        *alerts_service.drift_alerts(db, plant_id, bands, now=now, stage=stage),
        *alerts_service.pattern_alerts(db, plant_id, on_date=spec.end, stage=stage),
    ]
    view["alerts"] = alerts_service.rank_and_cap(stage_alerts, level=2)
    view["recurring_issues"] = (
        alerts_service.recurring_issues(db, plant_id, spec.start, spec.end, stage=stage)
        if spec.mode is not RangeMode.TODAY
        else []
    )
    view["alerts_panel_mode"] = "live" if spec.mode is RangeMode.TODAY else "recurring"
    return view


@router.get("/plants/{plant_id}/stages/{stage}/specifics")
def get_stage_specifics(
    plant_id: int,
    stage: Stage,
    range_mode: RangeMode = Query(RangeMode.TODAY, alias="range"),
    date_from: date | None = None,
    date_to: date | None = None,
    reason_code: str | None = None,
    as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Level 3 - the investigation. Hour rows, the causes panel with its event
    logs, and the parameters panel (or the worker and audit log at bundling).

    reason_code narrows the event log to one Pareto bar, which is how an expanded
    bar and a deep-linked alert both land on their evidence.
    """
    _require_plant(db, plant_id)
    now = _now(as_of)
    spec = _spec(range_mode, date_from, date_to, now)
    return specifics_service.stage_specifics(
        db, plant_id, stage, spec, now=now, reason_code=reason_code
    )


@router.get("/plants/{plant_id}/alerts")
def get_alerts(
    plant_id: int,
    level: int = Query(2, ge=1, le=3),
    stage: Stage | None = None,
    as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    """Every live alert at or below the requested level, sorted by rupee impact."""
    _require_plant(db, plant_id)
    now = _now(as_of)
    bands = load_bands(db, plant_id, on_date=now.date())

    collected = [
        *alerts_service.event_alerts(db, plant_id, now=now),
        *alerts_service.drift_alerts(db, plant_id, bands, now=now, stage=stage),
        *alerts_service.pattern_alerts(db, plant_id, on_date=now.date(), stage=stage),
    ]
    if stage is not None:
        collected = [alert for alert in collected if alert.stage == stage.value]

    cap = LEVEL_1_ALERT_CAP if level == 1 else None
    return alerts_service.rank_and_cap(collected, level=level, cap=cap)


class AcknowledgeRequest(BaseModel):
    alert_key: str
    acknowledged_by: str | None = None


@router.post("/plants/{plant_id}/alerts/acknowledge", status_code=201)
def acknowledge_alert(
    plant_id: int,
    payload: AcknowledgeRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Acknowledged means owned, and stops escalation to Level 1."""
    _require_plant(db, plant_id)
    record = alerts_service.acknowledge(
        db, plant_id, payload.alert_key, by=payload.acknowledged_by
    )
    return {
        "alert_key": record.alert_key,
        "acknowledged_at": record.acknowledged_at,
        "acknowledged_by": record.acknowledged_by,
    }


@router.get("/plants/{plant_id}/reason-picker")
def get_reason_picker(
    plant_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """The write action's vocabulary: downtime reason codes grouped by time
    category, with planned and unplanned kept apart.

    Machines measure time; humans explain it. Classification happens at Level 3
    via PATCH /time-logs/{id}.
    """
    from app.models import DowntimeReasonCode

    _require_plant(db, plant_id)
    codes = db.query(DowntimeReasonCode).order_by(DowntimeReasonCode.category, DowntimeReasonCode.code).all()

    grouped: dict[str, list[dict]] = {}
    for code in codes:
        grouped.setdefault(code.category.value, []).append(
            {"id": code.id, "code": code.code, "description": code.description}
        )
    return {
        "groups": [
            {
                "category": category,
                # Planned time is drawn grey wherever it appears, never red.
                "planned": category == "setup",
                "codes": entries,
            }
            for category, entries in grouped.items()
        ]
    }
