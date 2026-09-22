"""Level 2 - the stage view. One template, three stages.

Answers "which part of Boarding, Printing or Bundling is hurting?", for the plant
head and the shift supervisor. The template's defining element is the context
row, and specifically the current order card: an actual speed is only meaningful
next to the budgeted speed for that job. Without it every number invites an
argument; with it the same number invites a question.

Caps, enforced here so the UI cannot quietly grow: five KPI cards, two charts.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    DefectObservation,
    DefectReasonCode,
    DowntimeReasonCode,
    Machine,
    MachineRun,
    MetricDefinition,
    ParameterReading,
    QualityRecord,
    Shift,
    TimeLog,
)
from app.models.enums import MaterialType, Stage, TimeCategory
from app.services.dashboard import facts
from dataclasses import replace

from app.services.dashboard.bands import (
    Band,
    band_position,
    load_bands,
    rag_for,
    scale_for_days,
)
from app.services.dashboard.ranges import Granularity, RangeSpec
from app.services.dashboard.status import STAGE_LABELS, machine_states, stage_status_line

MAX_KPI_CARDS = 5


def _kpi(
    key: str,
    label: str,
    value: float | None,
    unit: str,
    bands: dict[str, Band],
    *,
    provisional: bool = False,
    sub: str | None = None,
    days: int = 1,
    target_override: float | None = None,
) -> dict:
    band = scale_for_days(bands.get(key), days)
    if target_override is not None and band is not None:
        # Some targets cannot be read off a table: production-to-date has to be
        # judged against the plan for the elapsed part of the period, or a KPI
        # checked an hour into a shift is red by arithmetic alone.
        ratio = target_override / band.target if band.target else 1.0
        band = replace(
            band,
            target=target_override,
            red_line=None if band.red_line is None else band.red_line * ratio,
        )
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "target": band.target if band else None,
        "red_line": band.red_line if band else None,
        "rag": rag_for(value, band),
        "lower_is_better": band.lower_is_better if band else False,
        "season_adjusted": band.season_adjusted if band else False,
        "provisional": provisional and value is not None,
        "sub": sub,
    }


def _ratio(numerator: float | None, denominator: float | None, scale: float = 100.0) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(scale * numerator / denominator, 2)


def parameters_chip(db: Session, plant_id: int, stage: Stage, bands: dict[str, Band], *, now) -> dict:
    """The operating-parameter layer summarised in one phrase: "3 in band, 1
    drifting". Bundling has no parameters, so it gets no chip."""
    if stage is Stage.BUNDLING:
        return {"applicable": False, "phrase": None, "in_band": 0, "drifting": 0, "no_data": 0}

    window_start = now - timedelta(hours=2)
    rows = (
        db.query(MetricDefinition.code, MetricDefinition.name, ParameterReading.value)
        .join(ParameterReading, ParameterReading.metric_definition_id == MetricDefinition.id)
        .join(Machine, Machine.id == ParameterReading.machine_id)
        .filter(
            Machine.plant_id == plant_id,
            Machine.stage == stage,
            MetricDefinition.category == "parameters",
            ParameterReading.recorded_at >= window_start,
            ParameterReading.recorded_at <= now,
        )
        .order_by(ParameterReading.recorded_at)
        .all()
    )

    latest: dict[str, float] = {}
    for code, _name, value in rows:
        latest[code] = value

    in_band = drifting = no_data = 0
    for code, value in latest.items():
        position = band_position(value, bands.get(code))
        if position == "in_band":
            in_band += 1
        elif position == "unknown":
            no_data += 1
        else:
            drifting += 1

    parts = []
    if in_band:
        parts.append(f"{in_band} in band")
    if drifting:
        parts.append(f"{drifting} drifting")
    if no_data:
        parts.append(f"{no_data} no data")

    return {
        "applicable": True,
        "phrase": ", ".join(parts) if parts else "no readings",
        "in_band": in_band,
        "drifting": drifting,
        "no_data": no_data,
    }


def downtime_pareto(
    db: Session, plant_id: int, start: date, end: date, stage: Stage, *, limit: int = 5
) -> list[dict]:
    """What do I fix first? Horizontal Pareto, planned time in grey.

    Painting a changeover the same colour as a breakdown is how dashboards lose
    the shop floor, so the planned flag rides on every bar.
    """
    rows = (
        db.query(
            DowntimeReasonCode.code,
            DowntimeReasonCode.description,
            DowntimeReasonCode.category,
            func.count(TimeLog.id),
            func.sum(TimeLog.duration_minutes),
        )
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .join(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == stage,
        )
        .group_by(DowntimeReasonCode.code, DowntimeReasonCode.description, DowntimeReasonCode.category)
        .order_by(func.sum(TimeLog.duration_minutes).desc())
        .limit(limit)
        .all()
    )

    total = sum(float(minutes or 0) for *_, minutes in rows) or 1.0
    cumulative = 0.0
    bars: list[dict] = []
    for code, description, category, count, minutes in rows:
        minutes = float(minutes or 0)
        cumulative += minutes
        bars.append(
            {
                "code": code,
                "label": description,
                "category": category.value,
                # Order changes and planned maintenance are grey, never red.
                "planned": category.value == "setup",
                "minutes": round(minutes, 0),
                "events": int(count),
                "share_pct": round(100 * minutes / total, 1),
                "cumulative_pct": round(100 * cumulative / total, 1),
            }
        )
    return bars


def defect_pareto(
    db: Session, plant_id: int, start: date, end: date, stage: Stage, *, limit: int = 5
) -> list[dict]:
    rows = (
        db.query(
            DefectReasonCode.code,
            DefectReasonCode.description,
            func.sum(DefectObservation.quantity),
        )
        .select_from(DefectObservation)
        .join(DefectReasonCode, DefectReasonCode.id == DefectObservation.reason_code_id)
        .join(QualityRecord, QualityRecord.id == DefectObservation.quality_record_id)
        .join(MachineRun, MachineRun.id == QualityRecord.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == stage,
        )
        .group_by(DefectReasonCode.code, DefectReasonCode.description)
        .order_by(func.sum(DefectObservation.quantity).desc())
        .limit(limit)
        .all()
    )

    total = sum(float(qty or 0) for *_, qty in rows) or 1.0
    cumulative = 0.0
    bars: list[dict] = []
    for code, description, quantity in rows:
        quantity = float(quantity or 0)
        cumulative += quantity
        bars.append(
            {
                "code": code,
                "label": description,
                "planned": False,
                "quantity": round(quantity, 0),
                "share_pct": round(100 * quantity / total, 1),
                "cumulative_pct": round(100 * cumulative / total, 1),
            }
        )
    return bars


def time_split_strip(
    db: Session, plant_id: int, start: date, end: date, stage: Stage
) -> list[dict]:
    """Where did the minutes go? A 100% stacked horizontal strip, per machine."""
    rows = (
        db.query(
            Machine.id,
            Machine.machine_code,
            Machine.name,
            TimeLog.category,
            func.sum(TimeLog.duration_minutes),
        )
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == stage,
        )
        .group_by(Machine.id, Machine.machine_code, Machine.name, TimeLog.category)
        .all()
    )

    by_machine: dict[int, dict] = {}
    for machine_id, code, name, category, minutes in rows:
        entry = by_machine.setdefault(
            machine_id,
            {"machine_id": machine_id, "machine_code": code, "name": name, "minutes": {}, "total": 0.0},
        )
        entry["minutes"][category.value] = round(float(minutes or 0), 0)
        entry["total"] += float(minutes or 0)

    for entry in by_machine.values():
        total = entry["total"] or 1.0
        entry["shares"] = {
            category: round(100 * minutes / total, 1) for category, minutes in entry["minutes"].items()
        }
        entry["total"] = round(entry["total"], 0)

    return sorted(by_machine.values(), key=lambda entry: entry["machine_code"])


def hourly_chart(
    db: Session, plant_id: int, spec: RangeSpec, stage: Stage
) -> list[dict]:
    """How did the hours go? Vertical bars against a takt line, cause-annotated -
    so the chart explains itself rather than needing a second screen.

    In Week/Month/Custom the bars become days.
    """
    if spec.granularity is Granularity.HOURLY:
        hours = facts.hourly_breakdown(db, plant_id, spec.start, stage)
        annotations = _hour_annotations(db, plant_id, spec.start, stage)
        return [
            {
                "bucket": f"{hour['hour']:02d}:00",
                "output": hour["lineal_metres"] if stage is Stage.BOARD_MANUFACTURING else hour["good_qty"],
                "running_minutes": round(hour["minutes_by_category"].get("running", 0.0), 0),
                "minutes_by_category": hour["minutes_by_category"],
                "annotation": annotations.get(hour["hour"]),
            }
            for hour in hours
        ]

    quality = facts.quality_by_day(db, plant_id, spec.start, spec.end, stage)
    time_split = facts.time_split_by_day(db, plant_id, spec.start, spec.end, stage)
    board = (
        facts.material_by_day(
            db, plant_id, spec.start, spec.end, stage=stage, material_type=MaterialType.BOARD
        )
        if stage is Stage.BOARD_MANUFACTURING
        else {}
    )

    buckets: list[dict] = []
    day = spec.start
    while day <= spec.end:
        good = quality.get(day, (0.0, 0.0))[0]
        buckets.append(
            {
                "bucket": day.isoformat(),
                "output": round(board.get(day, (0.0, 0.0))[1], 0) if board else round(good, 0),
                "running_minutes": round(time_split.get(day, {}).get("running", 0.0), 0),
                "minutes_by_category": time_split.get(day, {}),
                "annotation": None,
            }
        )
        day += timedelta(days=1)
    return buckets


def _hour_annotations(db: Session, plant_id: int, day: date, stage: Stage) -> dict[int, str]:
    """Labels an amber hour with the cause that made it amber, e.g.
    "splice failures 17:00-18:00"."""
    rows = (
        db.query(
            func.extract("hour", TimeLog.start_time),
            DowntimeReasonCode.description,
            func.sum(TimeLog.duration_minutes),
        )
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .join(DowntimeReasonCode, DowntimeReasonCode.id == TimeLog.reason_code_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date == day,
            Machine.stage == stage,
            TimeLog.category != TimeCategory.RUNNING,
        )
        .group_by(func.extract("hour", TimeLog.start_time), DowntimeReasonCode.description)
        .all()
    )

    worst: dict[int, tuple[str, float]] = {}
    for hour, description, minutes in rows:
        hour = int(hour)
        minutes = float(minutes or 0)
        if hour not in worst or minutes > worst[hour][1]:
            worst[hour] = (description, minutes)
    # Only annotate hours where the loss was material enough to explain the bar.
    return {hour: f"{label} ({minutes:.0f} min)" for hour, (label, minutes) in worst.items() if minutes >= 5}


def _boarding_kpis(
    db: Session, plant_id: int, spec: RangeSpec, bands: dict[str, Band], *, now: datetime
) -> list[dict]:
    stage = Stage.BOARD_MANUFACTURING
    time_split = facts.time_split_by_day(db, plant_id, spec.start, spec.end, stage, as_of=now)
    scheduled = facts.scheduled_minutes_by_day(db, plant_id, spec.start, spec.end, stage, as_of=now)
    quality = facts.quality_by_day(db, plant_id, spec.start, spec.end, stage)
    rate = facts.rate_efficiency_by_day(db, plant_id, spec.start, spec.end, stage)
    paper = facts.material_by_day(
        db, plant_id, spec.start, spec.end, stage=stage, material_type=MaterialType.KRAFT_PAPER
    )
    board = facts.material_by_day(
        db, plant_id, spec.start, spec.end, stage=stage, material_type=MaterialType.BOARD
    )

    running = sum(split.get("running", 0.0) for split in time_split.values())
    scheduled_total = sum(scheduled.values())
    good = sum(g for g, _ in quality.values())
    reject = sum(r for _, r in quality.values())
    weighted = sum(w for w, _ in rate.values())
    weight = sum(w for _, w in rate.values())
    paper_in = sum(i for i, _ in paper.values())
    board_out = sum(o for _, o in board.values())
    tonnes = board_out / 1000

    avg_speed = None
    if running > 0:
        metres = (
            db.query(func.coalesce(func.sum(MachineRun.lineal_metres), 0.0))
            .join(Machine, Machine.id == MachineRun.machine_id)
            .join(Shift, Shift.id == MachineRun.shift_id)
            .filter(
                Shift.plant_id == plant_id,
                Shift.shift_date >= spec.start,
                Shift.shift_date <= spec.end,
                Machine.stage == stage,
            )
            .scalar()
        ) or 0.0
        avg_speed = round(metres / running, 1)

    rate_eff = round(weighted / weight, 2) if weight else None
    provisional = spec.includes_today

    planned_tonnes = sum(
        facts.planned_tonnes_by_day(
            db,
            plant_id,
            spec.start,
            spec.end,
            bands["production_weight"].target if "production_weight" in bands else None,
            as_of=now,
        ).values()
    )

    return [
        _kpi(
            "production_weight",
            "Production",
            round(tonnes, 2),
            "t",
            bands,
            provisional=provisional,
            sub=f"plan {planned_tonnes:.1f} t so far" if planned_tonnes else "no plan set",
            target_override=round(planned_tonnes, 2) if planned_tonnes else None,
        ),
        _kpi(
            "average_running_speed",
            "Avg running speed",
            avg_speed,
            "m/min",
            bands,
            provisional=provisional,
            sub=f"{rate_eff}% of budgeted" if rate_eff else "no job standard",
        ),
        _kpi(
            "paper_yield_pct",
            "Paper yield",
            _ratio(board_out, paper_in),
            "%",
            bands,
            provisional=provisional,
            sub=f"{round(paper_in - board_out):.0f} kg lost",
        ),
        _kpi(
            "first_pass_good_board_pct",
            "First-pass good board",
            _ratio(good, good + reject),
            "%",
            bands,
            provisional=provisional,
        ),
        _kpi(
            "uptime_pct",
            "Uptime",
            _ratio(running, scheduled_total),
            "%",
            bands,
            provisional=provisional,
            sub=f"{running:.0f} of {scheduled_total:.0f} min",
        ),
    ]


def _printing_kpis(
    db: Session, plant_id: int, spec: RangeSpec, bands: dict[str, Band], *, now: datetime
) -> list[dict]:
    stage = Stage.PRINTING
    time_split = facts.time_split_by_day(db, plant_id, spec.start, spec.end, stage, as_of=now)
    quality = facts.quality_by_day(db, plant_id, spec.start, spec.end, stage)
    rate = facts.rate_efficiency_by_day(db, plant_id, spec.start, spec.end, stage)
    setups = facts.setups_by_day(db, plant_id, spec.start, spec.end, stage)

    good = sum(g for g, _ in quality.values())
    reject = sum(r for _, r in quality.values())
    weighted = sum(w for w, _ in rate.values())
    weight = sum(w for _, w in rate.values())
    setup_count = sum(count for count, _ in setups.values())
    setup_minutes = sum(minutes for _, minutes in setups.values())

    totals: dict[str, float] = {}
    for split in time_split.values():
        for category, minutes in split.items():
            totals[category] = totals.get(category, 0.0) + minutes
    shift_total = sum(totals.values()) or 1.0
    running_share = round(100 * totals.get("running", 0.0) / shift_total, 1)

    provisional = spec.includes_today

    return [
        _kpi(
            "run_rate_efficiency_pct",
            "Run-rate efficiency",
            round(weighted / weight, 2) if weight else None,
            "%",
            bands,
            provisional=provisional,
            sub="vs job standard",
        ),
        _kpi(
            "setups_count",
            "Setups",
            float(setup_count),
            "count",
            bands,
            provisional=provisional,
            sub=f"avg {setup_minutes / setup_count:.0f} min" if setup_count else "none",
        ),
        _kpi(
            "setups_avg_time",
            "Avg setup time",
            round(setup_minutes / setup_count, 1) if setup_count else None,
            "min",
            bands,
            provisional=provisional,
        ),
        _kpi(
            "first_pass_good_printed_pct",
            "First-pass good",
            _ratio(good, good + reject),
            "%",
            bands,
            provisional=provisional,
        ),
        _kpi(
            "conversion_waste_pct",
            "Conversion waste",
            _ratio(reject, good + reject),
            "%",
            bands,
            provisional=provisional,
            sub=f"running {running_share}% of shift",
        ),
    ]


def _bundling_kpis(
    db: Session, plant_id: int, spec: RangeSpec, bands: dict[str, Band], *, now: datetime
) -> list[dict]:
    stage = Stage.BUNDLING
    bundling = facts.bundling_by_day(db, plant_id, spec.start, spec.end)
    time_split = facts.time_split_by_day(db, plant_id, spec.start, spec.end, stage, as_of=now)

    bundles = sum(day["bundles"] for day in bundling.values())
    output_kg = sum(day["output_kg"] for day in bundling.values())
    worker_shifts = sum(day["worker_shifts"] for day in bundling.values())
    starvation = sum(day["starvation_minutes"] for day in bundling.values())
    accuracies = [day["count_accuracy_pct"] for day in bundling.values() if day["count_accuracy_pct"]]
    running = sum(split.get("running", 0.0) for split in time_split.values())

    provisional = spec.includes_today

    return [
        _kpi(
            "bundles_per_hour",
            "Bundles per hour",
            round(bundles / (running / 60), 1) if running else None,
            "bundles/hr",
            bands,
            provisional=provisional,
        ),
        _kpi(
            "output_per_worker_shift",
            "Output per worker",
            round(output_kg / worker_shifts, 1) if worker_shifts else None,
            "kg",
            bands,
            provisional=provisional,
            sub=f"{worker_shifts:.0f} worker-shifts",
        ),
        _kpi(
            "count_accuracy_pct",
            "Count accuracy",
            round(sum(accuracies) / len(accuracies), 2) if accuracies else None,
            "%",
            bands,
            provisional=provisional,
            sub="random audits",
        ),
        _kpi(
            "starvation_minutes",
            "Starvation time",
            round(starvation, 0),
            "min",
            bands,
            provisional=provisional,
            # Recorded at bundling but caused upstream, and the card says so.
            sub="waiting on printing",
        ),
    ]


KPI_BUILDERS = {
    Stage.BOARD_MANUFACTURING: _boarding_kpis,
    Stage.PRINTING: _printing_kpis,
    Stage.BUNDLING: _bundling_kpis,
}


def starvation_timeline(db: Session, plant_id: int, day: date) -> dict:
    """Bundling's starvation drawn above printing's downtime, so cause and effect
    align visually on one time axis."""
    bundling_waiting = (
        db.query(func.extract("hour", TimeLog.start_time), func.sum(TimeLog.duration_minutes))
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date == day,
            Machine.stage == Stage.BUNDLING,
            TimeLog.category == TimeCategory.WAITING,
        )
        .group_by(func.extract("hour", TimeLog.start_time))
        .all()
    )
    printing_down = (
        db.query(func.extract("hour", TimeLog.start_time), func.sum(TimeLog.duration_minutes))
        .select_from(TimeLog)
        .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date == day,
            Machine.stage == Stage.PRINTING,
            TimeLog.category.in_([TimeCategory.BREAKDOWN, TimeCategory.SETUP]),
        )
        .group_by(func.extract("hour", TimeLog.start_time))
        .all()
    )

    starvation = {int(hour): round(float(minutes or 0), 0) for hour, minutes in bundling_waiting}
    upstream = {int(hour): round(float(minutes or 0), 0) for hour, minutes in printing_down}
    hours = sorted(set(starvation) | set(upstream))
    return {
        "hours": [
            {
                "bucket": f"{hour:02d}:00",
                "starvation_minutes": starvation.get(hour, 0.0),
                "upstream_lost_minutes": upstream.get(hour, 0.0),
            }
            for hour in hours
        ]
    }


def stage_view(db: Session, plant_id: int, stage: Stage, spec: RangeSpec, *, now) -> dict:
    bands = load_bands(db, plant_id, on_date=spec.end)
    tiles = machine_states(db, plant_id, now=now, stage=stage)
    kpis = KPI_BUILDERS[stage](db, plant_id, spec, bands, now=now)[:MAX_KPI_CARDS]

    # The order card is the fairness device: the current job's spec and its
    # budgeted speed, sitting next to the actual.
    current_order = next((tile["current_order"] for tile in tiles if tile["current_order"]), None)

    if stage is Stage.BOARD_MANUFACTURING:
        charts = {
            "primary": {"kind": "hourly_bars", "data": hourly_chart(db, plant_id, spec, stage)},
            "secondary": {
                "kind": "pareto",
                "data": downtime_pareto(db, plant_id, spec.start, spec.end, stage),
            },
        }
    elif stage is Stage.PRINTING:
        charts = {
            "primary": {
                "kind": "time_split_strip",
                "data": time_split_strip(db, plant_id, spec.start, spec.end, stage),
            },
            "secondary": {"kind": "hourly_bars", "data": hourly_chart(db, plant_id, spec, stage)},
        }
    else:
        charts = {
            "primary": {"kind": "hourly_bars", "data": hourly_chart(db, plant_id, spec, stage)},
            "secondary": {
                "kind": "starvation_timeline",
                "data": starvation_timeline(db, plant_id, spec.end)["hours"],
            },
        }

    # A small 7-day trend of the stage's headline KPI, always 7 days regardless
    # of the selector, with 30 available on tap.
    trend_end = spec.end
    trend_start = trend_end - timedelta(days=6)
    trend = _stage_trend(db, plant_id, stage, trend_start, trend_end)

    return {
        "plant_id": plant_id,
        "stage": stage.value,
        "stage_label": STAGE_LABELS[stage],
        # The process flow across the top of every screen, live for all three
        # stages - not just the one being viewed.
        "status_line": stage_status_line(db, plant_id, now=now),
        "range": {
            "mode": spec.mode.value,
            "start": spec.start,
            "end": spec.end,
            "label": spec.label,
            "granularity": spec.granularity.value,
            "provisional": spec.includes_today,
        },
        "context_row": {
            "machines": tiles,
            "current_order": current_order,
            "parameters_chip": parameters_chip(db, plant_id, stage, bands, now=now),
            "staged_orders_today": (
                _staged_orders_count(db, plant_id, spec.end) if stage is Stage.BUNDLING else None
            ),
        },
        "kpis": kpis,
        "charts": charts,
        "trend_7d": trend,
        "defect_pareto": defect_pareto(db, plant_id, spec.start, spec.end, stage),
    }


def _staged_orders_count(db: Session, plant_id: int, day: date) -> int:
    from app.models import Order

    return (
        db.query(func.count(Order.id))
        .filter(
            Order.plant_id == plant_id,
            Order.order_complete_staged_at.isnot(None),
            func.date(Order.order_complete_staged_at) == day,
        )
        .scalar()
    ) or 0


def _stage_trend(db: Session, plant_id: int, stage: Stage, start: date, end: date) -> list[dict]:
    """Which direction are we moving? A line with a target band, same form at
    every level."""
    quality = facts.quality_by_day(db, plant_id, start, end, stage)
    time_split = facts.time_split_by_day(db, plant_id, start, end, stage)
    scheduled = facts.scheduled_minutes_by_day(db, plant_id, start, end, stage)
    rate = facts.rate_efficiency_by_day(db, plant_id, start, end, stage) if stage is not Stage.BUNDLING else {}

    points: list[dict] = []
    day = start
    while day <= end:
        good, reject = quality.get(day, (0.0, 0.0))
        weighted, weight = rate.get(day, (0.0, 0.0))
        points.append(
            {
                "date": day.isoformat(),
                "first_pass_good_pct": _ratio(good, good + reject),
                "uptime_pct": _ratio(
                    time_split.get(day, {}).get("running", 0.0), scheduled.get(day, 0.0)
                ),
                "rate_efficiency_pct": round(weighted / weight, 2) if weight else None,
            }
        )
        day += timedelta(days=1)
    return points
