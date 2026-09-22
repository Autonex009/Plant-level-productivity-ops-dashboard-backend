"""The alert engine.

Section 7.4 end to end. Four types, each with a hard threshold "so that alerting
is never a matter of opinion":

  event    machine down more than 15 continuous minutes, or an order at risk for
           its dispatch time. Visible at Level 1.
  breach   a rollup or stage KPI crossing its red line. Visible at Level 1 (plant
           rollups) or Level 2 (stage KPIs).
  drift    an operating parameter trending out of band. Born at Level 2, carries
           an acknowledge control, and is promoted to Level 1 only if nobody
           acted on it for 60 minutes.
  pattern  repetition detection - the same reason code recurring in a shift.
           Level 2 only.

Alerts are never stored. They are derived on every read, which is what makes
"alerts auto-clear when the condition clears" true by construction. The only
thing persisted is the acknowledgement (see models/alerts.py), matched back to a
live condition by a deterministic alert_key.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AlertAcknowledgement,
    DowntimeReasonCode,
    Machine,
    MachineRun,
    MetricDefinition,
    Order,
    ParameterReading,
    Shift,
    TimeLog,
)
from app.models.enums import Stage
from app.services.dashboard.bands import Band, band_position
from app.services.dashboard.status import STAGE_LABELS, machine_states

# Hard thresholds. Deliberately constants, not settings: the spec calls for them
# to be fixed per type and "never discretionary".
DOWN_ALERT_MINUTES = 15
DRIFT_ESCALATION_MINUTES = 60
PATTERN_MIN_OCCURRENCES = 3
ORDER_AT_RISK_HOURS = 8
# How far back an unstaged order still counts as actionable. Beyond this it is a
# data-hygiene problem for the ERP, not a thing a supervisor can fix this shift,
# and letting it alert forever crowds every live event off the panel.
ORDER_STALE_AFTER_DAYS = 3
DRIFT_LOOKBACK_MINUTES = 90

SEVERITY_ORDER = {"event": 3, "breach": 2, "drift": 1, "pattern": 0}

# A minute lost at each stage, relative to the pacemaker. Boarding sets the
# plant's ceiling; a printer stopping costs less because there is a second one
# and buffer stock ahead of it; bundling is the cheapest minute on the floor.
STAGE_DOWNTIME_WEIGHT = {
    Stage.BOARD_MANUFACTURING: 1.0,
    Stage.PRINTING: 0.5,
    Stage.BUNDLING: 0.25,
}


@dataclass
class Alert:
    """what + where + how long + status/first action, every time."""

    key: str
    type: str
    stage: str | None
    what: str
    where: str
    how_long: str | None
    action: str | None
    level: int  # the lowest level this alert is visible at
    impact_inr: float = 0.0
    machine_id: int | None = None
    machine_run_id: int | None = None
    at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    acknowledgeable: bool = False
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    escalated: bool = False
    metric_code: str | None = None
    context: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "type": self.type,
            "stage": self.stage,
            "what": self.what,
            "where": self.where,
            "how_long": self.how_long,
            "action": self.action,
            "level": self.level,
            "impact_inr": round(self.impact_inr, 0),
            "machine_id": self.machine_id,
            "machine_run_id": self.machine_run_id,
            "at": self.at,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "acknowledgeable": self.acknowledgeable,
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at,
            "escalated": self.escalated,
            "metric_code": self.metric_code,
            "context": self.context,
        }


def _acknowledgements(db: Session, plant_id: int) -> dict[str, datetime]:
    rows = (
        db.query(AlertAcknowledgement.alert_key, func.max(AlertAcknowledgement.acknowledged_at))
        .filter(AlertAcknowledgement.plant_id == plant_id)
        .group_by(AlertAcknowledgement.alert_key)
        .all()
    )
    return dict(rows)


def _minutes_phrase(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} min"
    hours, remainder = divmod(minutes, 60)
    return f"{hours}h {remainder:02d}m" if remainder else f"{hours}h"


def event_alerts(db: Session, plant_id: int, *, now: datetime) -> list[Alert]:
    """Machines down beyond the threshold, and orders at risk for their dispatch
    time. Both are facts, not judgements."""
    alerts: list[Alert] = []

    for tile in machine_states(db, plant_id, now=now):
        minutes = tile["minutes_in_state"]
        if tile["state"] == "down" and minutes is not None and minutes >= DOWN_ALERT_MINUTES:
            reason = tile["reason_code"]
            reason_text = reason["description"] if reason else "reason not yet classified"
            alerts.append(
                Alert(
                    key=f"event:down:{tile['machine_id']}",
                    type="event",
                    stage=tile["stage"],
                    what=f"{tile['name']} down",
                    where=tile["machine_code"],
                    how_long=_minutes_phrase(minutes),
                    action=(
                        f"{reason_text} - maintenance called"
                        if reason
                        else "Classify the stop at Level 3"
                    ),
                    level=1,
                    # A stopped pacemaker costs the plant its whole hourly
                    # output, so the minutes are priced at the plant rate and
                    # discounted for stages that are not the bottleneck.
                    impact_inr=(
                        minutes
                        * settings.downtime_cost_inr_per_minute
                        * STAGE_DOWNTIME_WEIGHT.get(Stage(tile["stage"]), 0.5)
                    ),
                    machine_id=tile["machine_id"],
                    machine_run_id=tile["current_run_id"],
                    at=tile["since"],
                    window_start=tile["since"],
                    window_end=now,
                    context={"reason_code": reason, "state": "down"},
                )
            )

    # Orders due soon that bundling has not staged yet, within the window where
    # somebody can still do something about them.
    horizon = (now + timedelta(hours=ORDER_AT_RISK_HOURS)).date()
    floor = now.date() - timedelta(days=ORDER_STALE_AFTER_DAYS)
    at_risk = (
        db.query(Order)
        .filter(
            Order.plant_id == plant_id,
            Order.order_complete_staged_at.is_(None),
            Order.due_date.isnot(None),
            Order.due_date <= horizon,
            Order.due_date >= floor,
        )
        .order_by(Order.due_date)
        .all()
    )
    for order in at_risk:
        overdue = order.due_date < now.date()
        alerts.append(
            Alert(
                key=f"event:order_at_risk:{order.id}",
                type="event",
                stage=Stage.BUNDLING.value,
                what=f"Order {order.order_number} {'overdue' if overdue else 'at risk'}",
                where=order.customer_name or "dispatch",
                how_long=f"due {order.due_date.strftime('%d %b')}",
                action="Not yet staged - check bundling queue",
                level=1,
                impact_inr=min(
                    (order.quantity_ordered or 0) * settings.order_at_risk_value_fraction,
                    settings.order_at_risk_cap_inr,
                ),
                at=now,
                context={
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "due_date": order.due_date.isoformat(),
                    "overdue": overdue,
                },
            )
        )

    return alerts


def breach_alerts(cards: list[dict], *, stage: Stage | None = None, level: int = 1) -> list[Alert]:
    """Any KPI card sitting past its red line. The card already carries the
    verdict, so this only turns red into a line of text."""
    alerts: list[Alert] = []
    for card in cards:
        if card.get("rag") != "red":
            continue
        stage_value = stage.value if stage else None
        alerts.append(
            Alert(
                key=f"breach:{stage_value or 'plant'}:{card['key']}",
                type="breach",
                stage=stage_value,
                what=f"{card['label']} {card['value']}{card['unit']}",
                where=STAGE_LABELS[stage] if stage else "Plant",
                how_long=f"red line {card['red_line']}{card['unit']}",
                action="Open the stage view to find the driver",
                level=level,
                impact_inr=abs(card["value"] or 0) if card["key"] == "cost_of_waste_inr" else 0.0,
                metric_code=card["key"],
                context={"target": card.get("target"), "red_line": card.get("red_line")},
            )
        )
    return alerts


def drift_alerts(
    db: Session,
    plant_id: int,
    bands: dict[str, Band],
    *,
    now: datetime,
    stage: Stage | None = None,
) -> list[Alert]:
    """Operating parameters trending out of band, phrased with consequence and
    first action - "Roll temp 168 -> 159 C over 40 min - warp risk - check steam
    trap". These are the early-warning layer: they predict the next period's
    quality and waste rather than measuring this one.
    """
    window_start = now - timedelta(minutes=DRIFT_LOOKBACK_MINUTES)

    query = (
        db.query(ParameterReading, MetricDefinition, Machine)
        .join(MetricDefinition, MetricDefinition.id == ParameterReading.metric_definition_id)
        .join(Machine, Machine.id == ParameterReading.machine_id)
        .filter(
            Machine.plant_id == plant_id,
            ParameterReading.recorded_at >= window_start,
            ParameterReading.recorded_at <= now,
            MetricDefinition.category == "parameters",
        )
    )
    if stage is not None:
        query = query.filter(Machine.stage == stage)

    readings_by_key: dict[tuple[int, str], list[ParameterReading]] = {}
    meta: dict[tuple[int, str], tuple[MetricDefinition, Machine]] = {}
    for reading, definition, machine in query.order_by(ParameterReading.recorded_at).all():
        key = (machine.id, definition.code)
        readings_by_key.setdefault(key, []).append(reading)
        meta[key] = (definition, machine)

    acknowledged = _acknowledgements(db, plant_id)
    alerts: list[Alert] = []

    for key, readings in readings_by_key.items():
        if len(readings) < 3:
            continue
        definition, machine = meta[key]
        band = bands.get(definition.code)
        if band is None or band.band_low is None or band.band_high is None:
            continue

        first, last = readings[0], readings[-1]
        position = band_position(last.value, band)
        span = band.band_high - band.band_low
        movement = last.value - first.value

        # Either already outside the band, or moving across more than a third of
        # it within the lookback window - the drift that precedes the defect.
        drifting = position != "in_band" or (span > 0 and abs(movement) > span / 3)
        if not drifting:
            continue

        minutes = round((last.recorded_at - first.recorded_at).total_seconds() / 60)
        alert_key = f"drift:{machine.id}:{definition.code}"
        acknowledged_at = acknowledged.get(alert_key)
        # Acknowledged means owned, and stops escalation. Unacknowledged for an
        # hour and the alert is promoted to Level 1.
        escalated = acknowledged_at is None and minutes >= DRIFT_ESCALATION_MINUTES

        alerts.append(
            Alert(
                key=alert_key,
                type="drift",
                stage=machine.stage.value,
                what=(
                    f"{definition.name} {round(first.value, 1)} -> {round(last.value, 1)} "
                    f"{definition.unit}"
                ),
                where=machine.machine_code,
                how_long=f"over {minutes} min",
                action=_drift_action(definition.code, position),
                level=1 if escalated else 2,
                machine_id=machine.id,
                at=last.recorded_at,
                window_start=first.recorded_at,
                window_end=last.recorded_at,
                acknowledgeable=True,
                acknowledged=acknowledged_at is not None,
                acknowledged_at=acknowledged_at,
                escalated=escalated,
                metric_code=definition.code,
                context={
                    "from": round(first.value, 2),
                    "to": round(last.value, 2),
                    "band_low": band.band_low,
                    "band_high": band.band_high,
                    "position": position,
                    "season_adjusted": band.season_adjusted,
                },
            )
        )

    return alerts


def _drift_action(metric_code: str, position: str) -> str:
    """Consequence plus the first thing to check. A drift alert that only reports
    a number makes the operator do the diagnosis twice."""
    playbook = {
        "roll_temperature": ("warp and delamination risk", "check steam trap"),
        "steam_pressure": ("board bond strength at risk", "check boiler and header valve"),
        "glue_gap": ("pin adhesion at risk", "check glue roll setting"),
        "moisture_pct": ("warp risk", "check dryer residence and paper store"),
    }
    consequence, first_action = playbook.get(metric_code, ("quality at risk", "check the machine"))
    direction = {"above": "running high", "below": "running low", "in_band": "drifting"}.get(
        position, "drifting"
    )
    return f"{direction} - {consequence} - {first_action}"


def pattern_alerts(
    db: Session, plant_id: int, *, on_date: date, stage: Stage | None = None
) -> list[Alert]:
    """Repetition detection - "3rd splice failure this shift, all on Reel stand 2".

    One stop is an event; the same stop three times is a different problem, and
    it is the second one that is worth a supervisor's attention.
    """
    query = (
        db.query(
            Machine.id,
            Machine.machine_code,
            Machine.stage,
            DowntimeReasonCode.code,
            DowntimeReasonCode.description,
            func.count(TimeLog.id),
            func.sum(TimeLog.duration_minutes),
            func.max(TimeLog.end_time),
        )
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .join(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
        .filter(Shift.plant_id == plant_id, Shift.shift_date == on_date)
    )
    if stage is not None:
        query = query.filter(Machine.stage == stage)

    rows = (
        query.group_by(
            Machine.id, Machine.machine_code, Machine.stage, DowntimeReasonCode.code, DowntimeReasonCode.description
        )
        .having(func.count(TimeLog.id) >= PATTERN_MIN_OCCURRENCES)
        .all()
    )

    alerts: list[Alert] = []
    for machine_id, machine_code, machine_stage, code, description, count, minutes, last_at in rows:
        alerts.append(
            Alert(
                key=f"pattern:{machine_id}:{code}:{on_date.isoformat()}",
                type="pattern",
                stage=machine_stage.value,
                what=f"{int(count)}x {description} today",
                where=f"all on {machine_code}",
                how_long=f"{int(minutes or 0)} min total",
                action="Same cause repeating - treat as one problem, not three",
                level=2,
                impact_inr=(
                    float(minutes or 0)
                    * settings.downtime_cost_inr_per_minute
                    * STAGE_DOWNTIME_WEIGHT.get(machine_stage, 0.5)
                ),
                machine_id=machine_id,
                at=last_at,
                context={"reason_code": code, "occurrences": int(count)},
            )
        )
    return alerts


def rank_and_cap(alerts: list[Alert], *, level: int, cap: int | None = None) -> list[dict]:
    """Sorted by rupee impact, capped at five visible for Level 1.

    Money first is the ordering the spec asks for: a dashboard that lists alerts
    chronologically makes the reader do the prioritising.
    """
    visible = [alert for alert in alerts if alert.level <= level]
    visible.sort(
        key=lambda alert: (-alert.impact_inr, -SEVERITY_ORDER.get(alert.type, 0), alert.key)
    )
    if cap is not None:
        visible = visible[:cap]
    return [alert.as_dict() for alert in visible]


def acknowledge(db: Session, plant_id: int, alert_key: str, *, by: str | None = None) -> AlertAcknowledgement:
    record = AlertAcknowledgement(
        plant_id=plant_id,
        alert_key=alert_key,
        acknowledged_by=by,
        acknowledged_at=datetime.now(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def recurring_issues(
    db: Session, plant_id: int, start: date, end: date, *, stage: Stage | None = None
) -> list[dict]:
    """What the alerts panel becomes in Week/Month/Custom: cause + event count +
    hours + approximate rupee impact + the tell-tale detail.

    The week's list is the Monday meeting agenda, so it is ordered by money and
    each row names the machine that dominates it.
    """
    query = (
        db.query(
            DowntimeReasonCode.code,
            DowntimeReasonCode.description,
            DowntimeReasonCode.category,
            Machine.stage,
            func.count(TimeLog.id),
            func.sum(TimeLog.duration_minutes),
        )
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .join(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
        .filter(Shift.plant_id == plant_id, Shift.shift_date >= start, Shift.shift_date <= end)
    )
    if stage is not None:
        query = query.filter(Machine.stage == stage)

    rows = (
        query.group_by(
            DowntimeReasonCode.code,
            DowntimeReasonCode.description,
            DowntimeReasonCode.category,
            Machine.stage,
        )
        .order_by(func.sum(TimeLog.duration_minutes).desc())
        .limit(20)
        .all()
    )

    issues: list[dict] = []
    for code, description, category, machine_stage, count, minutes in rows:
        minutes = float(minutes or 0)
        # The machine carrying most of this cause - the tell-tale detail that
        # turns a category into a place to go.
        worst_query = (
            db.query(Machine.machine_code, func.sum(TimeLog.duration_minutes))
            .select_from(TimeLog)
            .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
            .join(Machine, Machine.id == MachineRun.machine_id)
            .join(Shift, Shift.id == MachineRun.shift_id)
            .join(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
            .filter(
                Shift.plant_id == plant_id,
                Shift.shift_date >= start,
                Shift.shift_date <= end,
                DowntimeReasonCode.code == code,
                # The row being explained is one (cause, stage) pair, so the
                # share must be measured inside that same stage. Without this
                # filter a machine's minutes across every stage were divided by
                # one stage's minutes and the share could exceed 100%.
                Machine.stage == machine_stage,
            )
            .group_by(Machine.machine_code)
            .order_by(func.sum(TimeLog.duration_minutes).desc())
        )
        worst = worst_query.first()
        share = round(100 * float(worst[1]) / minutes, 0) if worst and minutes else None

        issues.append(
            {
                "code": code,
                "cause": description,
                "category": category.value,
                # Planned time is never painted red: a changeover is not a breakdown.
                "planned": category.value == "setup",
                "stage": machine_stage.value,
                "events": int(count),
                "hours": round(minutes / 60, 1),
                "impact_inr": round(
                    minutes
                    * settings.downtime_cost_inr_per_minute
                    * STAGE_DOWNTIME_WEIGHT.get(machine_stage, 0.5),
                    0,
                ),
                "tell_tale": (
                    f"{share:.0f}% of it on {worst[0]}" if worst and share else None
                ),
            }
        )

    issues.sort(key=lambda issue: -issue["impact_inr"])
    return issues
