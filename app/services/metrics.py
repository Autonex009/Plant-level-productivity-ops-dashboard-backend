"""Computes the spec's derived metrics from raw fact-table data.

Everything here reads MaterialFlow/TimeLog/QualityRecord/BundlingRecord/PowerReading
rows and produces the percentages the spec defines. Nothing here is stored as
its own fact — a metric is only ever recomputed from source data, except for
DailyPlantRollup, which is cached (see compute_daily_plant_rollup) so historical
trends stay stable.
"""

from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    BundlingRecord,
    DailyPlantRollup,
    DefectObservation,
    DefectReasonCode,
    Machine,
    MachineRun,
    MaterialFlow,
    PowerReading,
    QualityRecord,
    Shift,
)
from app.models.enums import MaterialType, PowerSource, Stage, TimeCategory
from app.models.production import TimeLog


def material_yield_pct(
    db: Session, machine_run_id: int, material_type: MaterialType | None = None
) -> float | None:
    """Good output / input across a run's material flows. Pass material_type to
    restrict to one material when a run tracks more than one (e.g. paper + starch)."""

    query = db.query(
        func.sum(MaterialFlow.input_qty),
        func.sum(MaterialFlow.output_qty),
    ).filter(MaterialFlow.machine_run_id == machine_run_id)
    if material_type is not None:
        query = query.filter(MaterialFlow.material_type == material_type)
    total_in, total_out = query.one()
    if not total_in:
        return None
    return round(100 * (total_out or 0) / total_in, 2)


def quality_pct(db: Session, machine_run_id: int) -> float | None:
    """First-pass good %: good_qty / (good_qty + reject_qty)."""

    record = db.query(QualityRecord).filter(QualityRecord.machine_run_id == machine_run_id).one_or_none()
    if record is None:
        return None
    total = record.good_qty + record.reject_qty
    if total == 0:
        return None
    return round(100 * record.good_qty / total, 2)


def running_minutes(db: Session, machine_run_id: int) -> float:
    total = (
        db.query(func.coalesce(func.sum(TimeLog.duration_minutes), 0.0))
        .filter(TimeLog.machine_run_id == machine_run_id, TimeLog.category == TimeCategory.RUNNING)
        .scalar()
    )
    return total or 0.0


def rate_efficiency_pct(db: Session, machine_run_id: int) -> float | None:
    """Actual throughput rate vs. the order's job-specific standard. The basis
    differs by stage, since "a flat standard is not applied": lineal metres/min
    for the corrugator (continuous), sheets/hr for printing (batch). Returns None
    when there's no order standard to compare against, or the run lacks the
    matching measurement (lineal_metres, or a quality record for sheet counts)."""

    run = db.get(MachineRun, machine_run_id)
    if run is None or run.order is None or run.order.standard_speed is None:
        return None

    minutes = running_minutes(db, machine_run_id)
    if minutes <= 0:
        return None

    if run.machine.stage == Stage.BOARD_MANUFACTURING:
        if run.lineal_metres is None:
            return None
        actual_rate = run.lineal_metres / minutes  # m/min
    elif run.machine.stage == Stage.PRINTING:
        record = db.query(QualityRecord).filter(QualityRecord.machine_run_id == machine_run_id).one_or_none()
        if record is None:
            return None
        actual_rate = (record.good_qty + record.reject_qty) / (minutes / 60)  # sheets/hr
    else:
        return None

    if run.order.standard_speed <= 0:
        return None
    return round(100 * actual_rate / run.order.standard_speed, 2)


def bundles_per_hour(db: Session, machine_run_id: int) -> float | None:
    record = db.query(BundlingRecord).filter(BundlingRecord.machine_run_id == machine_run_id).one_or_none()
    if record is None:
        return None
    minutes = running_minutes(db, machine_run_id)
    if minutes <= 0:
        return None
    return round(record.bundles_count / (minutes / 60), 2)


def output_per_worker_shift(db: Session, machine_run_id: int) -> float | None:
    record = db.query(BundlingRecord).filter(BundlingRecord.machine_run_id == machine_run_id).one_or_none()
    if record is None or record.output_kg is None or not record.worker_count:
        return None
    return round(record.output_kg / record.worker_count, 2)


def machine_run_metrics(db: Session, machine_run_id: int) -> dict[str, Any]:
    return {
        "machine_run_id": machine_run_id,
        "yield_pct": material_yield_pct(db, machine_run_id),
        "quality_pct": quality_pct(db, machine_run_id),
        "rate_efficiency_pct": rate_efficiency_pct(db, machine_run_id),
        "running_minutes": running_minutes(db, machine_run_id),
        "bundles_per_hour": bundles_per_hour(db, machine_run_id),
        "output_per_worker_shift": output_per_worker_shift(db, machine_run_id),
    }


def shift_uptime_pct(db: Session, shift_id: int) -> list[dict[str, Any]]:
    """Running time / scheduled time, per machine, for one shift."""

    shift = db.get(Shift, shift_id)
    if shift is None:
        return []

    rows = (
        db.query(MachineRun.machine_id, func.coalesce(func.sum(TimeLog.duration_minutes), 0.0))
        .join(TimeLog, TimeLog.machine_run_id == MachineRun.id)
        .filter(MachineRun.shift_id == shift_id, TimeLog.category == TimeCategory.RUNNING)
        .group_by(MachineRun.machine_id)
        .all()
    )
    return [
        {
            "machine_id": machine_id,
            "running_minutes": minutes,
            "scheduled_minutes": shift.scheduled_minutes,
            "uptime_pct": round(100 * minutes / shift.scheduled_minutes, 2) if shift.scheduled_minutes else None,
        }
        for machine_id, minutes in rows
    ]


def defect_pareto(
    db: Session,
    *,
    plant_id: int | None = None,
    stage: Stage | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    query = (
        db.query(
            DefectReasonCode.code,
            DefectReasonCode.description,
            func.sum(DefectObservation.quantity).label("total_quantity"),
        )
        .join(DefectObservation, DefectObservation.reason_code_id == DefectReasonCode.id)
        .join(QualityRecord, QualityRecord.id == DefectObservation.quality_record_id)
        .join(MachineRun, MachineRun.id == QualityRecord.machine_run_id)
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
    )
    if plant_id is not None:
        query = query.filter(Shift.plant_id == plant_id)
    if stage is not None:
        query = query.filter(Machine.stage == stage)
    if date_from is not None:
        query = query.filter(Shift.shift_date >= date_from)
    if date_to is not None:
        query = query.filter(Shift.shift_date <= date_to)

    rows = (
        query.group_by(DefectReasonCode.code, DefectReasonCode.description)
        .order_by(func.sum(DefectObservation.quantity).desc())
        .all()
    )
    return [{"code": code, "description": description, "quantity": float(qty)} for code, description, qty in rows]


def compute_daily_plant_rollup(
    db: Session,
    *,
    plant_id: int,
    rollup_date: date,
    paper_rate_per_kg: float | None = None,
) -> DailyPlantRollup:
    """Recomputes and upserts the four headline plant-level numbers for one day.

    waste_cost_inr is only populated when paper_rate_per_kg is supplied: the spec's
    formula (waste kg x paper rate + starch + power share) needs a cost rate that
    isn't part of this data model (no commercial/pricing table exists yet), so it's
    passed in per call rather than invented here.

    power_per_tonne_kwh assumes board output is recorded in kg (MaterialFlow.unit
    == "kg"); a plant recording output in a different unit won't get this figure.
    """

    shifts = db.query(Shift).filter(Shift.plant_id == plant_id, Shift.shift_date == rollup_date).all()
    shift_ids = [s.id for s in shifts]
    scheduled_minutes_total = sum(s.scheduled_minutes for s in shifts)
    run_ids = (
        [r.id for r in db.query(MachineRun).filter(MachineRun.shift_id.in_(shift_ids)).all()] if shift_ids else []
    )

    utilization = quality = rate_eff = overall_yield = productivity = None
    waste_cost = power_per_tonne = grid_share = None

    if run_ids:
        running_total = (
            db.query(func.coalesce(func.sum(TimeLog.duration_minutes), 0.0))
            .filter(TimeLog.machine_run_id.in_(run_ids), TimeLog.category == TimeCategory.RUNNING)
            .scalar()
        )
        utilization = round(100 * running_total / scheduled_minutes_total, 2) if scheduled_minutes_total else None

        good_total, reject_total = db.query(
            func.coalesce(func.sum(QualityRecord.good_qty), 0.0),
            func.coalesce(func.sum(QualityRecord.reject_qty), 0.0),
        ).filter(QualityRecord.machine_run_id.in_(run_ids)).one()
        quality = round(100 * good_total / (good_total + reject_total), 2) if (good_total + reject_total) else None

        paper_consumed = (
            db.query(func.coalesce(func.sum(MaterialFlow.input_qty), 0.0))
            .join(MachineRun, MachineRun.id == MaterialFlow.machine_run_id)
            .join(Machine, Machine.id == MachineRun.machine_id)
            .filter(
                MachineRun.id.in_(run_ids),
                MaterialFlow.material_type == MaterialType.KRAFT_PAPER,
                Machine.stage == Stage.BOARD_MANUFACTURING,
            )
            .scalar()
        )

        good_dispatched = (
            db.query(func.coalesce(func.sum(BundlingRecord.output_kg), 0.0))
            .join(MachineRun, MachineRun.id == BundlingRecord.machine_run_id)
            .filter(MachineRun.id.in_(run_ids))
            .scalar()
        )
        overall_yield = round(100 * good_dispatched / paper_consumed, 2) if paper_consumed else None

        weighted_sum = 0.0
        weight_total = 0.0
        for run_id in run_ids:
            eff = rate_efficiency_pct(db, run_id)
            if eff is None:
                continue
            minutes = running_minutes(db, run_id)
            weighted_sum += eff * minutes
            weight_total += minutes
        rate_eff = round(weighted_sum / weight_total, 2) if weight_total else None

        if utilization is not None and rate_eff is not None and quality is not None:
            productivity = round(utilization * rate_eff * quality / 10000, 2)

        if paper_rate_per_kg is not None and paper_consumed:
            paper_waste_kg = max(paper_consumed - good_dispatched, 0.0)
            waste_cost = round(paper_waste_kg * paper_rate_per_kg, 2)

        power_rows = (
            db.query(PowerReading.source, func.coalesce(func.sum(PowerReading.kwh), 0.0))
            .filter(PowerReading.plant_id == plant_id, func.date(PowerReading.recorded_at) == rollup_date)
            .group_by(PowerReading.source)
            .all()
        )
        power_by_source = dict(power_rows)
        total_kwh = sum(power_by_source.values())

        board_output_kg = (
            db.query(func.coalesce(func.sum(MaterialFlow.output_qty), 0.0))
            .join(MachineRun, MachineRun.id == MaterialFlow.machine_run_id)
            .join(Machine, Machine.id == MachineRun.machine_id)
            .filter(
                MachineRun.id.in_(run_ids),
                Machine.stage == Stage.BOARD_MANUFACTURING,
                MaterialFlow.unit == "kg",
            )
            .scalar()
        )
        tonnes_produced = board_output_kg / 1000
        power_per_tonne = round(total_kwh / tonnes_produced, 2) if tonnes_produced else None
        grid_share = (
            round(100 * power_by_source.get(PowerSource.GRID, 0.0) / total_kwh, 2) if total_kwh else None
        )

    rollup = (
        db.query(DailyPlantRollup)
        .filter_by(plant_id=plant_id, rollup_date=rollup_date)
        .one_or_none()
    )
    if rollup is None:
        rollup = DailyPlantRollup(plant_id=plant_id, rollup_date=rollup_date)
        db.add(rollup)

    rollup.overall_yield_pct = overall_yield
    rollup.utilization_pct = utilization
    rollup.rate_efficiency_pct = rate_eff
    rollup.quality_pct = quality
    rollup.plant_productivity_pct = productivity
    rollup.waste_cost_inr = waste_cost
    rollup.power_per_tonne_kwh = power_per_tonne
    rollup.grid_power_share_pct = grid_share

    db.commit()
    db.refresh(rollup)
    return rollup
