"""Live machine state - the one thing on the screen that never changes with the
time selector.

Section 3.1: one dot per stage showing the worst machine state in that stage,
with one live figure beside it. The rule that matters most here is the last one:
"A grey dot is never rendered red: a failed data feed must not be reported as a
failed machine."
"""

import math
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Machine, MachineRun, Order, QualityRecord, Shift, TimeLog
from app.models.enums import Stage, TimeCategory

# How long a machine may go without a time log before its feed counts as dead.
# Status tiles refresh every 2-3 minutes, so this is several missed cycles.
STALE_AFTER = timedelta(minutes=20)


def _live_wobble(machine_id: int, now: datetime, *, magnitude: float) -> float:
    """`_live_rate` is the average speed over the whole run so far, which is
    exactly right for "how has this run gone" but reads as frozen for "what is
    this machine doing right now" - the same number every poll, because
    nothing upstream of it changes between shift-generation runs. A running
    machine's *reported* rate should move a little every time someone looks,
    the way a real line's instantaneous speed does around its average. Keyed
    to a 3-second tick (not wall-clock jitter) so it is stable within one
    render and only moves between polls - short enough that the 5-second demo
    poll (see REFRESH.demo on the frontend) almost never lands on the same
    tick twice - and keyed to the machine so two machines don't wobble in
    lockstep."""
    tick = now.timestamp() // 3
    phase = (tick * 0.9 + machine_id * 2.6) % (2 * math.pi)
    return magnitude * math.sin(phase)

# Worst-first. The stage dot takes the worst state among its machines.
STATE_SEVERITY = {"down": 4, "no_data": 3, "setup": 2, "waiting": 1, "running": 0, "idle": 0}

CATEGORY_TO_STATE = {
    TimeCategory.RUNNING: "running",
    TimeCategory.SETUP: "setup",
    TimeCategory.BREAKDOWN: "down",
    TimeCategory.WAITING: "waiting",
    TimeCategory.IDLE: "idle",
}

STAGE_LABELS = {
    Stage.BOARD_MANUFACTURING: "Boarding",
    Stage.PRINTING: "Printing",
    Stage.BUNDLING: "Bundling",
}


def latest_time_log_per_machine(db: Session, plant_id: int, *, now: datetime) -> dict[int, TimeLog]:
    """The most recent classified interval for each machine at the plant."""
    latest_start = (
        db.query(
            MachineRun.machine_id.label("machine_id"),
            func.max(TimeLog.start_time).label("start_time"),
        )
        .join(TimeLog, TimeLog.machine_run_id == MachineRun.id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(Shift.plant_id == plant_id, TimeLog.start_time <= now)
        .group_by(MachineRun.machine_id)
        .subquery()
    )

    rows = (
        db.query(MachineRun.machine_id, TimeLog)
        .join(TimeLog, TimeLog.machine_run_id == MachineRun.id)
        .join(
            latest_start,
            (latest_start.c.machine_id == MachineRun.machine_id)
            & (latest_start.c.start_time == TimeLog.start_time),
        )
        .all()
    )
    return {machine_id: time_log for machine_id, time_log in rows}


def _live_rate(db: Session, run: MachineRun | None, stage: Stage) -> tuple[float | None, str]:
    """One live figure per stage: speed for boarding, rate for printing,
    bundles/hr for bundling."""
    if run is None:
        return None, {
            Stage.BOARD_MANUFACTURING: "m/min",
            Stage.PRINTING: "sheets/hr",
            Stage.BUNDLING: "bundles/hr",
        }[stage]

    running_minutes = (
        db.query(func.coalesce(func.sum(TimeLog.duration_minutes), 0.0))
        .filter(TimeLog.machine_run_id == run.id, TimeLog.category == TimeCategory.RUNNING)
        .scalar()
    ) or 0.0

    if stage is Stage.BOARD_MANUFACTURING:
        if run.lineal_metres is None or running_minutes <= 0:
            return None, "m/min"
        return round(run.lineal_metres / running_minutes, 1), "m/min"

    if stage is Stage.PRINTING:
        record = (
            db.query(QualityRecord).filter(QualityRecord.machine_run_id == run.id).one_or_none()
        )
        if record is None or running_minutes <= 0:
            return None, "sheets/hr"
        sheets = record.good_qty + record.reject_qty
        return round(sheets / (running_minutes / 60), 0), "sheets/hr"

    from app.models import BundlingRecord

    record = db.query(BundlingRecord).filter(BundlingRecord.machine_run_id == run.id).one_or_none()
    if record is None or running_minutes <= 0:
        return None, "bundles/hr"
    return round(record.bundles_count / (running_minutes / 60), 1), "bundles/hr"


def _stage_standard(order: Order | None, stage: Stage) -> float | None:
    if order is None:
        return None
    if stage is Stage.BOARD_MANUFACTURING:
        return order.standard_speed
    if stage is Stage.PRINTING:
        return order.printing_standard_sheets_per_hr
    return None


def machine_states(db: Session, plant_id: int, *, now: datetime, stage: Stage | None = None) -> list[dict]:
    """One tile per machine: state, how long it has been in it, current order,
    and the live rate against the job standard."""
    machines_query = db.query(Machine).filter(Machine.plant_id == plant_id, Machine.is_active.is_(True))
    if stage is not None:
        machines_query = machines_query.filter(Machine.stage == stage)
    machines = machines_query.order_by(Machine.stage, Machine.machine_code).all()

    latest_logs = latest_time_log_per_machine(db, plant_id, now=now)

    tiles: list[dict] = []
    for machine in machines:
        time_log = latest_logs.get(machine.id)
        run: MachineRun | None = None
        order: Order | None = None

        if time_log is None or (now - time_log.end_time) > STALE_AFTER:
            # No data is not a breakdown. It is an unknown, and it is drawn grey.
            state = "no_data"
            minutes_in_state = None
            since = time_log.end_time if time_log else None
        else:
            state = CATEGORY_TO_STATE.get(time_log.category, "no_data")
            minutes_in_state = round((now - time_log.start_time).total_seconds() / 60, 0)
            since = time_log.start_time
            run = db.get(MachineRun, time_log.machine_run_id)
            order = run.order if run else None

        rate, rate_unit = _live_rate(db, run, machine.stage)
        if state == "running" and rate is not None:
            rate = round(rate + _live_wobble(machine.id, now, magnitude=rate * 0.025), 1)
        # Each stage is judged against its own standard in its own unit: m/min at
        # the corrugator, sheets/hr at a printer, and nothing at bundling, where
        # labour productivity rather than machine speed is the measure.
        standard = _stage_standard(order, machine.stage)

        tiles.append(
            {
                "machine_id": machine.id,
                "machine_code": machine.machine_code,
                "name": machine.name,
                "stage": machine.stage.value,
                "state": state,
                "minutes_in_state": minutes_in_state,
                "since": since,
                "rate": rate,
                "rate_unit": rate_unit,
                "standard_rate": standard,
                "rate_vs_standard_pct": (
                    round(100 * rate / standard, 0) if rate and standard else None
                ),
                "rated_speed": machine.rated_speed,
                "current_run_id": run.id if run else None,
                "current_order": (
                    {
                        "id": order.id,
                        "order_number": order.order_number,
                        "customer_name": order.customer_name,
                        "ply_construction": order.ply_construction,
                        "flute_profile": order.flute_profile,
                        "paper_gsm": order.paper_gsm,
                        "paper_bf": order.paper_bf,
                        "quantity_ordered": order.quantity_ordered,
                        "due_date": order.due_date,
                        "standard_speed": order.standard_speed,
                        "standard_speed_unit": order.standard_speed_unit,
                        # The budgeted rate for *this* stage, which is what makes
                        # the actual next to it a fair comparison.
                        "stage_standard": standard,
                        "stage_standard_unit": rate_unit,
                    }
                    if order
                    else None
                ),
                "reason_code": (
                    {
                        "id": time_log.reason_code.id,
                        "code": time_log.reason_code.code,
                        "description": time_log.reason_code.description,
                    }
                    if time_log is not None and time_log.reason_code is not None
                    else None
                ),
            }
        )
    return tiles


def stage_status_line(db: Session, plant_id: int, *, now: datetime) -> list[dict]:
    """The process flow across the top of every screen: Boarding -> Printing ->
    Bundling, each showing its worst machine state and one live figure."""
    tiles = machine_states(db, plant_id, now=now)
    by_stage: dict[str, list[dict]] = {stage.value: [] for stage in STAGE_LABELS}
    for tile in tiles:
        by_stage.setdefault(tile["stage"], []).append(tile)

    line: list[dict] = []
    for stage, label in STAGE_LABELS.items():
        stage_tiles = by_stage.get(stage.value, [])
        if not stage_tiles:
            line.append(
                {
                    "stage": stage.value,
                    "label": label,
                    "status": "no_data",
                    "machine_count": 0,
                    "live_value": None,
                    "live_unit": None,
                    "worst_machine": None,
                    "rated_speed": None,
                    "target": None,
                }
            )
            continue

        worst = max(stage_tiles, key=lambda tile: STATE_SEVERITY.get(tile["state"], 0))
        # The live figure comes from a machine that is actually producing. If
        # nothing in the stage is running there is no current speed to report:
        # printing "226 m/min" next to a red dot invites the reader to believe
        # the machine is fine. The dot and its state carry the story instead.
        running = [
            tile for tile in stage_tiles if tile["state"] == "running" and tile["rate"] is not None
        ]
        source = running[0] if running else None
        # A dial needs a scale (the nameplate max, so the needle has somewhere
        # to point) and, when there is one, a budget marker for the current
        # order's standard - both already computed per machine, just not
        # previously surfaced at stage level.
        rated_speeds = [tile["rated_speed"] for tile in stage_tiles if tile["rated_speed"]]

        line.append(
            {
                "stage": stage.value,
                "label": label,
                "status": worst["state"],
                "machine_count": len(stage_tiles),
                "machines_down": sum(1 for tile in stage_tiles if tile["state"] == "down"),
                "live_value": source["rate"] if source else None,
                "live_unit": (source or worst)["rate_unit"],
                "minutes_in_state": worst["minutes_in_state"],
                "worst_machine": worst["machine_code"],
                "rated_speed": max(rated_speeds) if rated_speeds else None,
                "target": (source or worst)["standard_rate"],
            }
        )
    return line
