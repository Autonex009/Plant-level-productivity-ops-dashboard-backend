"""Day-grained aggregates over the fact tables.

Every dashboard number ultimately comes from here, so a figure shown at Level 1
and the same figure shown at Level 2 are the same query, not two definitions that
drift apart. Each function returns a mapping keyed by shift_date, which callers
either sum (range totals) or plot (trends).

Two conventions the spec forces:
  - Utilisation, rate efficiency and quality for *plant productivity* are scoped
    to the corrugator alone, since boarding is the pacemaker and sets the plant's
    ceiling; averaging across machines produces a number nobody owns.
  - Nothing here reads DailyPlantRollup. Trends and totals are recomputed from
    facts, so a number never depends on whether a rollup job has run.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import (
    BundlingRecord,
    Machine,
    MachineRun,
    MaterialFlow,
    Order,
    PowerReading,
    QualityRecord,
    Shift,
    TimeLog,
)
from app.models.enums import MaterialType, PowerSource, Stage, TimeCategory


def running_minutes_subquery(db: Session):
    """Running minutes per machine run - the denominator of every rate."""
    return (
        db.query(
            TimeLog.machine_run_id.label("run_id"),
            func.sum(TimeLog.duration_minutes).label("minutes"),
        )
        .filter(TimeLog.category == TimeCategory.RUNNING)
        .group_by(TimeLog.machine_run_id)
        .subquery()
    )


def _run_query(db: Session, *entities):
    """Starts a query rooted at MachineRun.

    These queries usually select a Shift column first, and select_from has to be
    applied before any join or filter. Without it SQLAlchemy roots the statement
    at shifts and leaves machine_runs out of the FROM clause entirely.
    """
    return db.query(*entities).select_from(MachineRun)


def _scoped(query, plant_id: int, start: date, end: date, stage: Stage | None):
    """Narrows a MachineRun-rooted query to one plant, date window, and stage."""
    query = query.join(Machine, Machine.id == MachineRun.machine_id).join(
        Shift, Shift.id == MachineRun.shift_id
    )
    query = query.filter(
        Shift.plant_id == plant_id,
        Shift.shift_date >= start,
        Shift.shift_date <= end,
    )
    if stage is not None:
        query = query.filter(Machine.stage == stage)
    return query


def time_split_by_day(
    db: Session,
    plant_id: int,
    start: date,
    end: date,
    stage: Stage | None = None,
    *,
    as_of: datetime | None = None,
) -> dict[date, dict[str, float]]:
    """Minutes by time category per day - the raw material for utilisation, the
    loss waterfall, and the run/setup/down/idle split.

    as_of truncates an interval that has not finished yet. It has to be applied
    on this side as well as to the scheduled-minutes denominator: clamping only
    the denominator lets a still-open interval contribute its full duration and
    pushes utilisation above 100%.
    """
    if as_of is None:
        duration = func.sum(TimeLog.duration_minutes)
    else:
        duration = func.sum(
            func.extract("epoch", func.least(TimeLog.end_time, as_of) - TimeLog.start_time) / 60
        )

    query = _scoped(
        _run_query(db, Shift.shift_date, TimeLog.category, duration).join(
            TimeLog, TimeLog.machine_run_id == MachineRun.id
        ),
        plant_id,
        start,
        end,
        stage,
    )
    if as_of is not None:
        query = query.filter(TimeLog.start_time <= as_of)

    rows = query.group_by(Shift.shift_date, TimeLog.category).all()

    result: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for day, category, minutes in rows:
        result[day][category.value] += float(minutes or 0)
    return {day: dict(split) for day, split in result.items()}


def scheduled_minutes_by_day(
    db: Session,
    plant_id: int,
    start: date,
    end: date,
    stage: Stage | None = None,
    *,
    as_of: datetime | None = None,
) -> dict[date, float]:
    """Scheduled minutes summed over every machine of the stage rostered on that
    shift. One corrugator on a 480-minute shift gives 480, two give 960, so
    utilisation stays a fraction of available machine-time either way.

    A shift still in progress only counts the minutes that have actually elapsed.
    Without that, utilisation read an hour into a shift would divide one hour of
    running by eight hours of roster and show 12% - a number that is arithmetically
    true, permanently red every morning, and useless. Passing as_of keeps the
    in-progress figure honest; it turns into the full roster once the shift closes.
    """
    rows = (
        _scoped(
            _run_query(
                db,
                Shift.shift_date,
                Shift.scheduled_minutes,
                Shift.start_time,
                func.count(func.distinct(MachineRun.machine_id)),
            ),
            plant_id,
            start,
            end,
            stage,
        )
        .group_by(Shift.shift_date, Shift.id, Shift.scheduled_minutes, Shift.start_time)
        .all()
    )

    result: dict[date, float] = defaultdict(float)
    for day, scheduled, shift_start, machine_count in rows:
        available = float(scheduled)
        if as_of is not None and as_of < shift_start + timedelta(minutes=available):
            elapsed = (as_of - shift_start).total_seconds() / 60
            available = max(0.0, min(available, elapsed))
        result[day] += available * int(machine_count)
    return dict(result)


def quality_by_day(
    db: Session, plant_id: int, start: date, end: date, stage: Stage | None = None
) -> dict[date, tuple[float, float]]:
    """(good_qty, reject_qty) per day."""
    rows = (
        _scoped(
            _run_query(
                db,
                Shift.shift_date,
                func.sum(QualityRecord.good_qty),
                func.sum(QualityRecord.reject_qty),
            ).join(QualityRecord, QualityRecord.machine_run_id == MachineRun.id),
            plant_id,
            start,
            end,
            stage,
        )
        .group_by(Shift.shift_date)
        .all()
    )
    return {day: (float(good or 0), float(reject or 0)) for day, good, reject in rows}


def rate_efficiency_by_day(
    db: Session,
    plant_id: int,
    start: date,
    end: date,
    stage: Stage = Stage.BOARD_MANUFACTURING,
) -> dict[date, tuple[float, float]]:
    """(weighted_sum, weight) per day, so a range total is a running-minute
    weighted mean rather than a mean of means.

    Weighting each run's efficiency by its own running minutes collapses the
    algebra: efficiency x minutes = (metres / minutes / standard) x minutes, so
    the weighted sum is just 100 x sum(metres / standard) for the corrugator, and
    100 x 60 x sum(sheets / standard) for a printer measured in sheets/hr.
    """
    minutes = running_minutes_subquery(db)

    if stage is Stage.BOARD_MANUFACTURING:
        # Continuous machine: lineal metres against a m/min standard.
        numerator = func.sum(MachineRun.lineal_metres / Order.standard_speed) * 100
        query = _scoped(
            _run_query(db, Shift.shift_date, numerator, func.sum(minutes.c.minutes))
            .join(Order, Order.id == MachineRun.order_id)
            .join(minutes, minutes.c.run_id == MachineRun.id),
            plant_id,
            start,
            end,
            stage,
        ).filter(MachineRun.lineal_metres.isnot(None), Order.standard_speed > 0)
    elif stage is Stage.PRINTING:
        # Batch machine: sheets against the job's sheets/hr standard, hence the
        # x60. Order.standard_speed is the corrugator's m/min figure for the same
        # job and must never appear in this ratio.
        sheets = QualityRecord.good_qty + QualityRecord.reject_qty
        numerator = func.sum(sheets / Order.printing_standard_sheets_per_hr) * 100 * 60
        query = _scoped(
            _run_query(db, Shift.shift_date, numerator, func.sum(minutes.c.minutes))
            .join(Order, Order.id == MachineRun.order_id)
            .join(QualityRecord, QualityRecord.machine_run_id == MachineRun.id)
            .join(minutes, minutes.c.run_id == MachineRun.id),
            plant_id,
            start,
            end,
            stage,
        ).filter(Order.printing_standard_sheets_per_hr > 0)
    else:
        # Bundling has no speed standard; labour productivity is its measure.
        return {}

    rows = query.group_by(Shift.shift_date).all()
    return {day: (float(weighted or 0), float(weight or 0)) for day, weighted, weight in rows}


def material_by_day(
    db: Session,
    plant_id: int,
    start: date,
    end: date,
    *,
    stage: Stage,
    material_type: MaterialType,
    unit: str = "kg",
) -> dict[date, tuple[float, float]]:
    """(input_qty, output_qty) per day for one material at one stage - the mass
    balance whose difference is that stage's waste."""
    rows = (
        _scoped(
            _run_query(
                db,
                Shift.shift_date,
                func.sum(MaterialFlow.input_qty),
                func.sum(func.coalesce(MaterialFlow.output_qty, 0.0)),
            ).join(MaterialFlow, MaterialFlow.machine_run_id == MachineRun.id),
            plant_id,
            start,
            end,
            stage,
        )
        .filter(MaterialFlow.material_type == material_type, MaterialFlow.unit == unit)
        .group_by(Shift.shift_date)
        .all()
    )
    return {day: (float(inp or 0), float(out or 0)) for day, inp, out in rows}


def dispatched_kg_by_day(db: Session, plant_id: int, start: date, end: date) -> dict[date, float]:
    """Good output actually staged for dispatch - the numerator of overall yield."""
    rows = (
        _scoped(
            _run_query(db, Shift.shift_date, func.sum(BundlingRecord.output_kg)).join(
                BundlingRecord, BundlingRecord.machine_run_id == MachineRun.id
            ),
            plant_id,
            start,
            end,
            Stage.BUNDLING,
        )
        .group_by(Shift.shift_date)
        .all()
    )
    return {day: float(kg or 0) for day, kg in rows}


def bundling_by_day(db: Session, plant_id: int, start: date, end: date) -> dict[date, dict]:
    """Bundles, workers, starvation minutes and count accuracy per day."""
    rows = (
        _scoped(
            _run_query(
                db,
                Shift.shift_date,
                func.sum(BundlingRecord.bundles_count),
                func.sum(BundlingRecord.output_kg),
                func.sum(BundlingRecord.worker_count),
                func.sum(BundlingRecord.starvation_minutes),
                func.avg(BundlingRecord.count_accuracy_pct),
            ).join(BundlingRecord, BundlingRecord.machine_run_id == MachineRun.id),
            plant_id,
            start,
            end,
            Stage.BUNDLING,
        )
        .group_by(Shift.shift_date)
        .all()
    )

    return {
        day: {
            "bundles": float(bundles or 0),
            "output_kg": float(output or 0),
            "worker_shifts": float(workers or 0),
            "starvation_minutes": float(starvation or 0),
            "count_accuracy_pct": float(accuracy) if accuracy is not None else None,
        }
        for day, bundles, output, workers, starvation, accuracy in rows
    }


def power_by_day(db: Session, plant_id: int, start: date, end: date) -> dict[date, dict[str, float]]:
    """kWh split by grid and DG. Genset hours are pure margin leakage, so the DG
    share is carried separately rather than folded into a single total."""
    day_expr = func.date(PowerReading.recorded_at)
    rows = (
        db.query(
            day_expr,
            func.sum(case((PowerReading.source == PowerSource.GRID, PowerReading.kwh), else_=0.0)),
            func.sum(case((PowerReading.source == PowerSource.DG, PowerReading.kwh), else_=0.0)),
            func.count(case((PowerReading.source == PowerSource.DG, 1))),
        )
        .filter(PowerReading.plant_id == plant_id, day_expr >= start, day_expr <= end)
        .group_by(day_expr)
        .all()
    )

    def _as_date(value) -> date:
        return value if isinstance(value, date) else datetime.fromisoformat(str(value)).date()

    return {
        _as_date(day): {
            "grid_kwh": float(grid or 0),
            "dg_kwh": float(dg or 0),
            "dg_reading_count": int(dg_count or 0),
        }
        for day, grid, dg, dg_count in rows
    }


def setups_by_day(
    db: Session, plant_id: int, start: date, end: date, stage: Stage
) -> dict[date, tuple[int, float]]:
    """(count, total_minutes) of setup/changeover intervals. Printing lives or
    dies by these: a machine rated at 6,000 sheets/hr can deliver 2,500 across a
    shift on plate changes, ink changes, and short order runs alone."""
    rows = (
        _scoped(
            _run_query(
                db,
                Shift.shift_date,
                func.count(TimeLog.id),
                func.sum(TimeLog.duration_minutes),
            ).join(TimeLog, TimeLog.machine_run_id == MachineRun.id),
            plant_id,
            start,
            end,
            stage,
        )
        .filter(TimeLog.category == TimeCategory.SETUP)
        .group_by(Shift.shift_date)
        .all()
    )
    return {day: (int(count or 0), float(minutes or 0)) for day, count, minutes in rows}


def planned_tonnes_by_day(
    db: Session,
    plant_id: int,
    start: date,
    end: date,
    target_tonnes_per_shift: float | None,
    *,
    as_of: datetime | None = None,
) -> dict[date, float]:
    """The plan line for the flight path: the plant's configured production
    standard multiplied by the shifts actually rostered that day.

    A shift in progress contributes only the fraction of its plan that its
    elapsed minutes have earned, so "behind plan" means behind, rather than
    merely part-way through the shift.
    """
    if not target_tonnes_per_shift:
        return {}
    rows = (
        db.query(Shift.shift_date, Shift.start_time, Shift.scheduled_minutes)
        .filter(Shift.plant_id == plant_id, Shift.shift_date >= start, Shift.shift_date <= end)
        .all()
    )

    result: dict[date, float] = defaultdict(float)
    for day, shift_start, scheduled in rows:
        fraction = 1.0
        if as_of is not None and scheduled:
            elapsed = (as_of - shift_start).total_seconds() / 60
            fraction = max(0.0, min(1.0, elapsed / float(scheduled)))
        result[day] += target_tonnes_per_shift * fraction
    return dict(result)


def board_output_tonnes_by_day(db: Session, plant_id: int, start: date, end: date) -> dict[date, float]:
    flows = material_by_day(
        db,
        plant_id,
        start,
        end,
        stage=Stage.BOARD_MANUFACTURING,
        material_type=MaterialType.BOARD,
    )
    return {day: output / 1000 for day, (_, output) in flows.items()}


def hourly_breakdown(db: Session, plant_id: int, day: date, stage: Stage) -> list[dict]:
    """Minutes by category and apportioned output, bucketed by hour of the day.

    Feeds the Level 2 "how did the hours go?" bars and the Level 3 hour rows.
    Counters are read per run rather than per hour, so a run's output is split
    across the hours it ran in proportion to the running minutes in each.
    """
    hour_expr = func.extract("hour", TimeLog.start_time)

    category_rows = (
        _scoped(
            _run_query(db, hour_expr.label("hour"), TimeLog.category, func.sum(TimeLog.duration_minutes))
            .join(TimeLog, TimeLog.machine_run_id == MachineRun.id),
            plant_id,
            day,
            day,
            stage,
        )
        .group_by("hour", TimeLog.category)
        .all()
    )
    minutes_by_hour: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for hour, category, minutes in category_rows:
        minutes_by_hour[int(hour)][category.value] += float(minutes or 0)

    run_totals_rows = (
        _scoped(
            _run_query(
                db,
                MachineRun.id,
                func.coalesce(MachineRun.lineal_metres, 0.0),
                func.coalesce(QualityRecord.good_qty, 0.0),
            ).outerjoin(QualityRecord, QualityRecord.machine_run_id == MachineRun.id),
            plant_id,
            day,
            day,
            stage,
        ).all()
    )
    run_output = {run_id: (float(metres or 0), float(good or 0)) for run_id, metres, good in run_totals_rows}

    run_hour_rows = (
        _scoped(
            _run_query(db, MachineRun.id, hour_expr.label("hour"), func.sum(TimeLog.duration_minutes))
            .join(TimeLog, TimeLog.machine_run_id == MachineRun.id),
            plant_id,
            day,
            day,
            stage,
        )
        .filter(TimeLog.category == TimeCategory.RUNNING)
        .group_by(MachineRun.id, "hour")
        .all()
    )

    run_running_total: dict[int, float] = defaultdict(float)
    for run_id, _hour, minutes in run_hour_rows:
        run_running_total[run_id] += float(minutes or 0)

    output_by_hour: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for run_id, hour, minutes in run_hour_rows:
        total = run_running_total.get(run_id, 0.0)
        if total <= 0:
            continue
        share = float(minutes or 0) / total
        metres, good = run_output.get(run_id, (0.0, 0.0))
        output_by_hour[int(hour)]["lineal_metres"] += metres * share
        output_by_hour[int(hour)]["good_qty"] += good * share

    hours = sorted(set(minutes_by_hour) | set(output_by_hour))
    return [
        {
            "hour": hour,
            "minutes_by_category": dict(minutes_by_hour.get(hour, {})),
            "lineal_metres": round(output_by_hour.get(hour, {}).get("lineal_metres", 0.0), 1),
            "good_qty": round(output_by_hour.get(hour, {}).get("good_qty", 0.0), 1),
        }
        for hour in hours
    ]
