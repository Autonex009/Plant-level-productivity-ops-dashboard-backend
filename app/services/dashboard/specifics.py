"""Level 3 - stage specifics.

Levels 1 and 2 judge performance; Level 3 investigates it. Three panels sharing
one time axis, plus the system's only write action (reason classification, which
is the CRUD PATCH on a time log rather than anything new here).

This is where every alert lands: the panel opens with the time window
pre-selected and the related events highlighted. Alert to root cause in one tap
is the single interaction the whole architecture is built to serve.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    BundlingRecord,
    DowntimeReasonCode,
    Machine,
    MachineRun,
    MaterialFlow,
    MetricDefinition,
    Order,
    ParameterReading,
    QualityRecord,
    Shift,
    TimeLog,
)
from app.models.enums import MaterialType, Stage, TimeCategory
from app.services.dashboard import facts
from app.services.dashboard.bands import Band, band_position, load_bands
from app.services.dashboard.ranges import Granularity, RangeSpec
from app.services.dashboard.stage import defect_pareto, downtime_pareto


def _output_unit(stage: Stage) -> str:
    """What this stage actually counts: metres off the corrugator, sheets off a
    printer, bundles off the bundling line."""
    return {
        Stage.BOARD_MANUFACTURING: "m",
        Stage.PRINTING: "sheets",
        Stage.BUNDLING: "bundles",
    }[stage]


def hour_rows(db: Session, plant_id: int, spec: RangeSpec, stage: Stage) -> list[dict]:
    """Every hour of the shift as a row: output, a state timeline, and the events
    that occurred. The factual record of where the time went.

    In Week/Month/Custom the rows become days.
    """
    if spec.granularity is Granularity.HOURLY:
        breakdown = facts.hourly_breakdown(db, plant_id, spec.start, stage)
        events = _events_by_hour(db, plant_id, spec.start, stage)
        return [
            {
                "bucket": f"{hour['hour']:02d}:00",
                "hour": hour["hour"],
                "date": spec.start.isoformat(),
                "output": (
                    hour["lineal_metres"] if stage is Stage.BOARD_MANUFACTURING else hour["good_qty"]
                ),
                "output_unit": _output_unit(stage),
                "segments": _segments(hour["minutes_by_category"]),
                "events": events.get(hour["hour"], []),
            }
            for hour in breakdown
        ]

    time_split = facts.time_split_by_day(db, plant_id, spec.start, spec.end, stage)
    quality = facts.quality_by_day(db, plant_id, spec.start, spec.end, stage)
    board = (
        facts.material_by_day(
            db, plant_id, spec.start, spec.end, stage=stage, material_type=MaterialType.BOARD
        )
        if stage is Stage.BOARD_MANUFACTURING
        else {}
    )

    rows: list[dict] = []
    day = spec.start
    while day <= spec.end:
        good = quality.get(day, (0.0, 0.0))[0]
        rows.append(
            {
                "bucket": day.strftime("%d %b"),
                "hour": None,
                "date": day.isoformat(),
                "output": round(board.get(day, (0.0, 0.0))[1], 0) if board else round(good, 0),
                "output_unit": "kg" if board else _output_unit(stage),
                "segments": _segments(time_split.get(day, {})),
                "events": [],
            }
        )
        day += timedelta(days=1)
    return rows


def _segments(minutes_by_category: dict[str, float]) -> list[dict]:
    """run / setup / down / waiting / idle as coloured segments, always in that
    order so the eye compares rows without re-reading the legend."""
    order = ["running", "setup", "breakdown", "waiting", "idle"]
    total = sum(minutes_by_category.values()) or 1.0
    return [
        {
            "category": category,
            "minutes": round(minutes_by_category.get(category, 0.0), 0),
            "share_pct": round(100 * minutes_by_category.get(category, 0.0) / total, 1),
        }
        for category in order
        if minutes_by_category.get(category)
    ]


def _events_by_hour(db: Session, plant_id: int, day: date, stage: Stage) -> dict[int, list[dict]]:
    rows = (
        db.query(TimeLog, Machine.machine_code, DowntimeReasonCode, Order.order_number)
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .outerjoin(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
        .outerjoin(Order, Order.id == MachineRun.order_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date == day,
            Machine.stage == stage,
            TimeLog.category != TimeCategory.RUNNING,
        )
        .order_by(TimeLog.start_time)
        .all()
    )

    events: dict[int, list[dict]] = {}
    for time_log, machine_code, reason, order_number in rows:
        events.setdefault(time_log.start_time.hour, []).append(
            {
                "time_log_id": time_log.id,
                "machine_code": machine_code,
                "category": time_log.category.value,
                "start_time": time_log.start_time,
                "end_time": time_log.end_time,
                "duration_minutes": round(time_log.duration_minutes, 0),
                "reason_code": reason.code if reason else None,
                "reason": reason.description if reason else None,
                # An unclassified stop is the work item, not a gap in the data.
                "needs_classification": reason is None and time_log.category != TimeCategory.IDLE,
                "order_number": order_number,
            }
        )
    return events


def downtime_events(
    db: Session, plant_id: int, start: date, end: date, stage: Stage, *, reason_code: str | None = None
) -> list[dict]:
    """The evidence under a Pareto bar: start time, duration, reason code,
    operator comment, and the order that was running."""
    query = (
        db.query(TimeLog, Machine.machine_code, DowntimeReasonCode, Order.order_number)
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .outerjoin(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
        .outerjoin(Order, Order.id == MachineRun.order_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == stage,
            TimeLog.category != TimeCategory.RUNNING,
        )
    )
    if reason_code is not None:
        query = query.filter(DowntimeReasonCode.code == reason_code)

    return [
        {
            "time_log_id": time_log.id,
            "machine_run_id": time_log.machine_run_id,
            "machine_code": machine_code,
            "category": time_log.category.value,
            "start_time": time_log.start_time,
            "end_time": time_log.end_time,
            "duration_minutes": round(time_log.duration_minutes, 0),
            "reason_code_id": time_log.reason_code_id,
            "reason_code": reason.code if reason else None,
            "reason": reason.description if reason else None,
            "needs_classification": reason is None and time_log.category != TimeCategory.IDLE,
            "order_number": order_number,
        }
        for time_log, machine_code, reason, order_number in query.order_by(TimeLog.start_time.desc())
        .limit(200)
        .all()
    ]


def parameter_strips(
    db: Session, plant_id: int, stage: Stage, bands: dict[str, Band], *, now: datetime
) -> list[dict]:
    """The early-warning layer as value-in-band strips: current value, control
    band, and a drift arrow with the trend of the last hours.

    Bundling has no parameters; the caller replaces this panel with the worker
    and audit log instead.
    """
    if stage is Stage.BUNDLING:
        return []

    window_start = now - timedelta(hours=8)
    rows = (
        db.query(ParameterReading, MetricDefinition, Machine)
        .join(MetricDefinition, MetricDefinition.id == ParameterReading.metric_definition_id)
        .join(Machine, Machine.id == ParameterReading.machine_id)
        .filter(
            Machine.plant_id == plant_id,
            Machine.stage == stage,
            ParameterReading.recorded_at >= window_start,
            ParameterReading.recorded_at <= now,
            MetricDefinition.category.in_(["parameters", "quality"]),
        )
        .order_by(ParameterReading.recorded_at)
        .all()
    )

    grouped: dict[tuple[int, str], dict] = {}
    for reading, definition, machine in rows:
        key = (machine.id, definition.code)
        entry = grouped.setdefault(
            key,
            {
                "machine_id": machine.id,
                "machine_code": machine.machine_code,
                "metric_code": definition.code,
                "label": definition.name,
                "unit": definition.unit,
                "source": reading.source.value,
                "series": [],
            },
        )
        entry["series"].append({"at": reading.recorded_at, "value": round(reading.value, 2)})

    strips: list[dict] = []
    for entry in grouped.values():
        band = bands.get(entry["metric_code"])
        series = entry["series"]
        current = series[-1]["value"]
        # The drift arrow compares the last reading with the start of the window,
        # scaled against the band so a wide band is not called drifting too soon.
        earliest = series[0]["value"]
        span = (band.band_high - band.band_low) if band and band.band_low is not None and band.band_high is not None else None
        movement = current - earliest
        if span and abs(movement) > span / 6:
            drift = "rising" if movement > 0 else "falling"
        else:
            drift = "steady"

        strips.append(
            {
                **entry,
                "value": current,
                "band_low": band.band_low if band else None,
                "band_high": band.band_high if band else None,
                "target": band.target if band else None,
                "position": band_position(current, band),
                "season_adjusted": band.season_adjusted if band else False,
                "drift": drift,
                "change": round(movement, 2),
                "series": series[-40:],
                "last_checked_at": series[-1]["at"],
            }
        )

    strips.sort(key=lambda strip: (strip["position"] == "in_band", strip["label"]))
    return strips


def order_run_log(db: Session, plant_id: int, start: date, end: date, stage: Stage) -> list[dict]:
    """Per-order run log: what each job actually did against what it was supposed
    to do. Boarding shows metres and speed vs budget; printing shows sheets and
    rate vs standard."""
    minutes_sub = facts.running_minutes_subquery(db)

    rows = (
        db.query(
            MachineRun,
            Machine.machine_code,
            Order,
            QualityRecord,
            func.coalesce(minutes_sub.c.minutes, 0.0),
        )
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .outerjoin(Order, Order.id == MachineRun.order_id)
        .outerjoin(QualityRecord, QualityRecord.machine_run_id == MachineRun.id)
        .outerjoin(minutes_sub, minutes_sub.c.run_id == MachineRun.id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == stage,
        )
        .order_by(MachineRun.start_time.desc())
        .limit(100)
        .all()
    )

    # The mass balance for every run on screen, fetched in one pass rather than
    # one query per row.
    run_ids = [run.id for run, *_ in rows]
    waste_by_run: dict[int, float] = {}
    if run_ids:
        for run_id, input_qty, output_qty in (
            db.query(
                MaterialFlow.machine_run_id,
                func.sum(MaterialFlow.input_qty),
                func.sum(func.coalesce(MaterialFlow.output_qty, 0.0)),
            )
            .filter(MaterialFlow.machine_run_id.in_(run_ids), MaterialFlow.unit == "kg")
            .group_by(MaterialFlow.machine_run_id)
            .all()
        ):
            waste_by_run[run_id] = round(max(float(input_qty or 0) - float(output_qty or 0), 0.0), 1)

    log: list[dict] = []
    for run, machine_code, order, quality, running_minutes in rows:
        running_minutes = float(running_minutes or 0)
        actual_rate = None
        standard = None
        if order is not None:
            standard = (
                order.standard_speed
                if stage is Stage.BOARD_MANUFACTURING
                else order.printing_standard_sheets_per_hr
            )

        if stage is Stage.BOARD_MANUFACTURING and run.lineal_metres and running_minutes:
            actual_rate = round(run.lineal_metres / running_minutes, 1)
        elif stage is Stage.PRINTING and quality and running_minutes:
            actual_rate = round((quality.good_qty + quality.reject_qty) / (running_minutes / 60), 0)

        log.append(
            {
                "machine_run_id": run.id,
                "machine_code": machine_code,
                "order_number": order.order_number if order else None,
                "customer_name": order.customer_name if order else None,
                "ply_construction": order.ply_construction if order else None,
                "flute_profile": order.flute_profile if order else None,
                "start_time": run.start_time,
                "end_time": run.end_time,
                "running_minutes": round(running_minutes, 0),
                "lineal_metres": run.lineal_metres,
                "good_qty": quality.good_qty if quality else None,
                "reject_qty": quality.reject_qty if quality else None,
                "unit": quality.unit if quality else None,
                "actual_rate": actual_rate,
                "standard_rate": standard,
                "rate_vs_standard_pct": (
                    round(100 * actual_rate / standard, 0) if actual_rate and standard else None
                ),
                "waste_kg": waste_by_run.get(run.id),
            }
        )
    return log


def setup_log(db: Session, plant_id: int, start: date, end: date) -> list[dict]:
    """Each printing setup: job from/to, duration, versus target. Changeovers are
    where a batch stage's capacity actually goes."""
    rows = (
        db.query(TimeLog, Machine.machine_code, Order.order_number, DowntimeReasonCode)
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .outerjoin(Order, Order.id == MachineRun.order_id)
        .outerjoin(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == Stage.PRINTING,
            TimeLog.category == TimeCategory.SETUP,
        )
        .order_by(TimeLog.start_time.desc())
        .limit(60)
        .all()
    )

    entries: list[dict] = []
    previous_order_by_machine: dict[str, str | None] = {}
    for time_log, machine_code, order_number, reason in rows:
        entries.append(
            {
                "time_log_id": time_log.id,
                "machine_code": machine_code,
                "start_time": time_log.start_time,
                "duration_minutes": round(time_log.duration_minutes, 0),
                "job_to": order_number,
                "job_from": previous_order_by_machine.get(machine_code),
                "reason": reason.description if reason else "Job changeover",
            }
        )
        previous_order_by_machine[machine_code] = order_number
    return entries


def ink_check_log(db: Session, plant_id: int, start: date, end: date, *, now: datetime) -> list[dict]:
    """Printing's parameter panel is the ink check log: viscosity by Ford cup
    No. 4 and pH, each check timestamped, with overdue checks flagged."""
    rows = (
        db.query(ParameterReading, MetricDefinition, Machine)
        .join(MetricDefinition, MetricDefinition.id == ParameterReading.metric_definition_id)
        .join(Machine, Machine.id == ParameterReading.machine_id)
        .filter(
            Machine.plant_id == plant_id,
            Machine.stage == Stage.PRINTING,
            func.date(ParameterReading.recorded_at) >= start,
            func.date(ParameterReading.recorded_at) <= end,
        )
        .order_by(ParameterReading.recorded_at.desc())
        .limit(80)
        .all()
    )

    latest_by_machine: dict[str, datetime] = {}
    checks: list[dict] = []
    for reading, definition, machine in rows:
        latest_by_machine.setdefault(machine.machine_code, reading.recorded_at)
        checks.append(
            {
                "machine_code": machine.machine_code,
                "metric_code": definition.code,
                "label": definition.name,
                "value": round(reading.value, 2),
                "unit": definition.unit,
                "recorded_at": reading.recorded_at,
                "source": reading.source.value,
            }
        )

    # A check not taken is itself the finding, so overdue machines ride along.
    overdue = [
        {"machine_code": code, "last_checked_at": at, "hours_since": round((now - at).total_seconds() / 3600, 1)}
        for code, at in latest_by_machine.items()
        if (now - at) > timedelta(hours=4)
    ]
    return [{"checks": checks, "overdue": overdue}]


def staged_orders(db: Session, plant_id: int, start: date, end: date) -> list[dict]:
    """Orders staged with completion timestamps - the basis of on-time delivery
    reporting."""
    rows = (
        db.query(Order)
        .filter(
            Order.plant_id == plant_id,
            Order.order_complete_staged_at.isnot(None),
            func.date(Order.order_complete_staged_at) >= start,
            func.date(Order.order_complete_staged_at) <= end,
        )
        .order_by(Order.order_complete_staged_at.desc())
        .limit(80)
        .all()
    )
    return [
        {
            "order_id": order.id,
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "quantity_ordered": order.quantity_ordered,
            "due_date": order.due_date,
            "staged_at": order.order_complete_staged_at,
            "on_time": (
                order.order_complete_staged_at.date() <= order.due_date if order.due_date else None
            ),
        }
        for order in rows
    ]


def worker_and_audit_log(db: Session, plant_id: int, start: date, end: date) -> list[dict]:
    """Bundling's replacement for the parameters panel: output per worker and the
    count-audit results, plus each starvation event linked to its upstream cause."""
    rows = (
        db.query(BundlingRecord, MachineRun, Machine.machine_code, Shift.shift_date, Shift.shift_number)
        .join(MachineRun, MachineRun.id == BundlingRecord.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(Shift.plant_id == plant_id, Shift.shift_date >= start, Shift.shift_date <= end)
        .order_by(Shift.shift_date.desc(), Shift.shift_number.desc())
        .limit(60)
        .all()
    )
    return [
        {
            "machine_run_id": record.machine_run_id,
            "machine_code": machine_code,
            "shift_date": shift_date,
            "shift_number": shift_number,
            "worker_count": record.worker_count,
            "bundles_count": record.bundles_count,
            "output_kg": record.output_kg,
            "output_per_worker": (
                round(record.output_kg / record.worker_count, 1)
                if record.output_kg and record.worker_count
                else None
            ),
            "count_accuracy_pct": record.count_accuracy_pct,
            "starvation_minutes": record.starvation_minutes,
        }
        for record, _run, machine_code, shift_date, shift_number in rows
    ]


def starvation_events(db: Session, plant_id: int, start: date, end: date) -> list[dict]:
    """Each starvation event linked to the upstream machine and event that caused
    it. Recorded at bundling, owned by printing."""
    waits = (
        db.query(TimeLog, Machine.machine_code)
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == Stage.BUNDLING,
            TimeLog.category == TimeCategory.WAITING,
        )
        .order_by(TimeLog.start_time.desc())
        .limit(50)
        .all()
    )

    events: list[dict] = []
    for wait, machine_code in waits:
        # The upstream stop that overlaps this wait is the cause worth naming.
        cause = (
            db.query(TimeLog, Machine.machine_code, DowntimeReasonCode)
            .select_from(TimeLog)
            .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
            .join(Machine, Machine.id == MachineRun.machine_id)
            .outerjoin(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
            .filter(
                Machine.plant_id == plant_id,
                Machine.stage == Stage.PRINTING,
                TimeLog.category != TimeCategory.RUNNING,
                TimeLog.start_time <= wait.end_time,
                TimeLog.end_time >= wait.start_time,
            )
            .order_by(TimeLog.duration_minutes.desc())
            .first()
        )
        events.append(
            {
                "time_log_id": wait.id,
                "machine_code": machine_code,
                "start_time": wait.start_time,
                "end_time": wait.end_time,
                "duration_minutes": round(wait.duration_minutes, 0),
                "caused_by": (
                    {
                        "machine_code": cause[1],
                        "category": cause[0].category.value,
                        "reason": cause[2].description if cause[2] else None,
                        "time_log_id": cause[0].id,
                        "duration_minutes": round(cause[0].duration_minutes, 0),
                    }
                    if cause
                    else None
                ),
            }
        )
    return events


def stage_specifics(
    db: Session,
    plant_id: int,
    stage: Stage,
    spec: RangeSpec,
    *,
    now: datetime,
    reason_code: str | None = None,
) -> dict:
    bands = load_bands(db, plant_id, on_date=spec.end)

    causes = {
        "downtime_pareto": downtime_pareto(db, plant_id, spec.start, spec.end, stage, limit=8),
        "defect_pareto": defect_pareto(db, plant_id, spec.start, spec.end, stage, limit=8),
        "events": downtime_events(db, plant_id, spec.start, spec.end, stage, reason_code=reason_code),
    }

    extras: dict = {}
    if stage is Stage.BOARD_MANUFACTURING:
        extras = {"run_log": order_run_log(db, plant_id, spec.start, spec.end, stage)}
    elif stage is Stage.PRINTING:
        extras = {
            "run_log": order_run_log(db, plant_id, spec.start, spec.end, stage),
            "setup_log": setup_log(db, plant_id, spec.start, spec.end),
            "ink_checks": ink_check_log(db, plant_id, spec.start, spec.end, now=now)[0],
        }
    else:
        extras = {
            "staged_orders": staged_orders(db, plant_id, spec.start, spec.end),
            "worker_log": worker_and_audit_log(db, plant_id, spec.start, spec.end),
            "starvation_events": starvation_events(db, plant_id, spec.start, spec.end),
        }

    return {
        "plant_id": plant_id,
        "stage": stage.value,
        "range": {
            "mode": spec.mode.value,
            "start": spec.start,
            "end": spec.end,
            "label": spec.label,
            "granularity": spec.granularity.value,
            "provisional": spec.includes_today,
        },
        "hour_rows": hour_rows(db, plant_id, spec, stage),
        "causes": causes,
        # Bundling has no parameters; its panel is the worker and audit log,
        # which the caller finds under extras.
        "parameters": parameter_strips(db, plant_id, stage, bands, now=now),
        "extras": extras,
    }
