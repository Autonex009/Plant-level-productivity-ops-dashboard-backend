"""Brings the live end of the demo dataset up to the present moment.

`advance_to_today` fills in whole missing *days*, and deliberately leaves a day
that already has shifts alone. That keeps history stable, but it means the
current shift stops wherever the last run happened to finish - and Machine
Monitoring, whose whole question is "what is happening right now", greys every
machine out once its newest time log is more than STALE_AFTER old. This tops up
that last gap.

Strictly additive. It never updates or deletes a row: it reuses the current
shift and the order already running on each machine, and writes a *new*
MachineRun with its own time logs, mass balance, quality record and parameter
readings covering only the window between where that machine's timeline stopped
and now. Re-running it is safe - the second call simply finds a smaller gap.

The clock matters more than usual here. The deployed API reads `datetime.now()`
inside a Vercel function, which runs in UTC, and it ignores any time log
starting in the future. Data written against a local non-UTC clock is therefore
either invisible or wrong, so this defaults to UTC and says which clock it used.

    python -m scripts.top_up_live                  # dry run, prints the plan
    python -m scripts.top_up_live --commit         # actually writes
    python -m scripts.top_up_live --commit --local-clock
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import BundlingRecord, MachineRun, MaterialFlow, Order, Shift, TimeLog
from app.models.enums import MaterialType, Stage, TimeCategory
from scripts.seed_demo import (
    RNG,
    SHIFT_MINUTES,
    SHIFTS,
    _add_ink_checks,
    _add_parameters,
    _add_quality,
    _build_run,
    _day_character,
    _fill_shift_minutes,
    _load_master_data,
)

# Below this there is nothing worth writing; the page is already live.
MIN_GAP_MINUTES = 2


def _current_shift_window(now: datetime) -> tuple[int, datetime, datetime]:
    """Which of the day's three shifts `now` falls inside."""
    for number, start_time, _end_time in SHIFTS:
        start = datetime.combine(now.date(), start_time)
        end = start + timedelta(minutes=SHIFT_MINUTES)
        if start <= now < end:
            return number, start, end
    # Past the last shift boundary only when SHIFTS does not cover the day.
    number, start_time, _ = SHIFTS[-1]
    start = datetime.combine(now.date(), start_time)
    return number, start, start + timedelta(minutes=SHIFT_MINUTES)


def top_up_live(db: Session, now: datetime, *, commit: bool) -> dict:
    loaded = _load_master_data(db)
    if loaded is None:
        return {"status": "skipped", "reason": "no plant found - run a full seed first"}
    plant, machines, downtime_codes, defect_codes, definitions = loaded

    shift_number, shift_start, shift_end = _current_shift_window(now)

    shift = (
        db.query(Shift)
        .filter(
            Shift.plant_id == plant.id,
            Shift.shift_date == now.date(),
            Shift.shift_number == shift_number,
        )
        .one_or_none()
    )
    created_shift = False
    if shift is None:
        # Adding the shift this moment belongs to is still additive - it is a
        # row that does not exist yet, not a change to one that does.
        shift = Shift(
            plant_id=plant.id,
            shift_date=now.date(),
            shift_number=shift_number,
            start_time=shift_start,
            end_time=shift_end,
            scheduled_minutes=SHIFT_MINUTES,
        )
        db.add(shift)
        db.flush()
        created_shift = True

    character = _day_character(now.date())
    added: list[dict] = []

    for machine in machines:
        if not machine.is_active:
            continue

        # Where this machine's timeline currently stops, inside this shift.
        newest_end = (
            db.query(func.max(TimeLog.end_time))
            .join(MachineRun, MachineRun.id == TimeLog.machine_run_id)
            .filter(MachineRun.machine_id == machine.id, MachineRun.shift_id == shift.id)
            .scalar()
        )
        resume_from = max(newest_end or shift_start, shift_start)
        gap_minutes = int((now - resume_from).total_seconds() / 60)
        if gap_minutes < MIN_GAP_MINUTES:
            added.append({"machine": machine.machine_code, "gap_minutes": gap_minutes, "action": "already live"})
            continue

        # Reuse the order this machine was last running rather than inventing
        # one, so the top-up does not inflate the order book.
        order = (
            db.query(Order)
            .join(MachineRun, MachineRun.order_id == Order.id)
            .filter(MachineRun.machine_id == machine.id, MachineRun.shift_id == shift.id)
            .order_by(MachineRun.start_time.desc())
            .first()
        ) or (
            db.query(Order)
            .filter(Order.plant_id == plant.id)
            .order_by(Order.id.desc())
            .first()
        )
        if order is None:
            added.append({"machine": machine.machine_code, "action": "skipped - no order to run"})
            continue

        segments = _fill_shift_minutes(
            resume_from,
            gap_minutes,
            health=character["health"],
            downtime_codes=downtime_codes,
            stage=machine.stage,
        )
        if not segments:
            continue

        run = _build_run(db, machine, shift, order, resume_from, segments, downtime_codes)
        running_minutes = sum(s[3] for s in segments if s[0] is TimeCategory.RUNNING)

        if machine.stage is Stage.BOARD_MANUFACTURING:
            standard = order.standard_speed or 200.0
            speed = standard * (0.68 + 0.30 * character["health"]) * RNG.uniform(0.94, 1.06)
            run.lineal_metres = round(speed * running_minutes, 1)

            width_m, gsm = 1.6, (order.paper_gsm or 140.0)
            plies = 5 if (order.ply_construction or "3-ply").startswith("5") else 3
            board_kg = run.lineal_metres * width_m * gsm * plies / 1000
            waste = 0.055 + (0.03 if character["monsoon"] else 0.0) + RNG.uniform(0, 0.03)
            paper_kg = board_kg / (1 - waste) if board_kg else 0.0

            db.add_all(
                [
                    MaterialFlow(
                        machine_run_id=run.id,
                        material_type=MaterialType.KRAFT_PAPER,
                        input_qty=round(paper_kg, 1),
                        output_qty=round(board_kg, 1),
                        unit="kg",
                    ),
                    MaterialFlow(
                        machine_run_id=run.id,
                        material_type=MaterialType.BOARD,
                        input_qty=round(paper_kg, 1),
                        output_qty=round(board_kg, 1),
                        unit="kg",
                    ),
                ]
            )
            _add_quality(
                db,
                run,
                total=max(int(run.lineal_metres / 1.3), 1),
                good_fraction=0.93 + 0.055 * character["health"],
                unit="sheets",
                stage=machine.stage,
                defect_codes=defect_codes,
                monsoon=character["monsoon"],
            )
            _add_parameters(db, machine, run, resume_from, gap_minutes, character, definitions)

        elif machine.stage is Stage.PRINTING:
            job_standard = order.printing_standard_sheets_per_hr or 4500.0
            sheets = int(job_standard * (running_minutes / 60) * RNG.uniform(0.78, 1.02))
            _add_quality(
                db,
                run,
                total=max(sheets, 1),
                good_fraction=0.955 + 0.03 * character["health"],
                unit="sheets",
                stage=machine.stage,
                defect_codes=defect_codes,
                monsoon=character["monsoon"],
            )
            _add_ink_checks(db, machine, run, resume_from, gap_minutes, definitions)

        else:
            workers = RNG.randint(6, 10)
            bundles = max(int(running_minutes / 60 * RNG.uniform(48, 64)), 1)
            db.add(
                BundlingRecord(
                    machine_run_id=run.id,
                    worker_count=workers,
                    bundles_count=bundles,
                    output_kg=round(bundles * RNG.uniform(9.0, 12.0), 1),
                    count_accuracy_pct=round(RNG.uniform(98.4, 99.9), 2),
                    starvation_minutes=round(
                        sum(s[3] for s in segments if s[0] is TimeCategory.WAITING), 1
                    ),
                )
            )
            _add_quality(
                db,
                run,
                total=bundles,
                good_fraction=0.99,
                unit="bundles",
                stage=machine.stage,
                defect_codes=defect_codes,
                monsoon=character["monsoon"],
            )

        added.append(
            {
                "machine": machine.machine_code,
                "gap_minutes": gap_minutes,
                "from": str(resume_from),
                "to": str(segments[-1][2]),
                "ends_as": segments[-1][0].value,
                "segments": len(segments),
            }
        )

    if commit:
        db.commit()
    else:
        db.rollback()

    return {
        "status": "committed" if commit else "dry-run (rolled back)",
        "now": str(now),
        "shift": f"{now.date()} shift {shift_number}",
        "created_shift": created_shift,
        "machines": added,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", action="store_true", help="write the rows (default: dry run)")
    parser.add_argument(
        "--local-clock",
        action="store_true",
        help="use the local clock instead of UTC (only if the API also runs local time)",
    )
    args = parser.parse_args()

    now = (
        datetime.now()
        if args.local_clock
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )
    print(f"clock: {'local' if args.local_clock else 'UTC'} -> {now}")

    with SessionLocal() as db:
        result = top_up_live(db, now, commit=args.commit)

    print(f"status: {result['status']}")
    if result.get("shift"):
        print(f"shift : {result['shift']} (created: {result.get('created_shift')})")
    for row in result.get("machines", []):
        print("  " + ", ".join(f"{k}={v}" for k, v in row.items()))


if __name__ == "__main__":
    main()
