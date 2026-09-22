"""Generates a plausible operating history for one corrugation plant.

This is demo and development data, not a fixture: it simulates a plant rather
than hand-writing rows, so the dashboard's derived numbers (yield, U x R x Q,
Paretos, drift) come out of the same arithmetic a real plant would produce.

What it models deliberately:
  - Paper is 60-65% of the cost of a box, and Indian plants lose 14-15% of it.
    Waste here averages around 12% and is split across the stages that cause it.
  - Boarding is the pacemaker, so its downtime starves printing, and printing's
    downtime starves bundling. Those links are written as real overlapping time
    logs, which is what lets Level 3 name a starvation event's upstream cause.
  - Monsoon months run measurably worse on moisture, warp and yield, so the
    season-adjusted bands have something to prove themselves against.
  - Today's shift is generated only up to the current clock time, so the live
    status line has a machine genuinely mid-run.

Usage:
    python -m scripts.seed_demo              # 60 days ending today
    python -m scripts.seed_demo --days 90
    python -m scripts.seed_demo --reset      # wipe existing data first
"""

from __future__ import annotations

import argparse
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.models import (
    Base,
    BundlingRecord,
    DefectObservation,
    DefectReasonCode,
    DowntimeReasonCode,
    Machine,
    MachineRun,
    MaterialFlow,
    MetricDefinition,
    Order,
    ParameterReading,
    Plant,
    PlantMetricTarget,
    PowerReading,
    QualityRecord,
    Shift,
    TimeLog,
)
from app.models.enums import (
    LineType,
    MaterialType,
    ParameterSource,
    PowerSource,
    Stage,
    TimeCategory,
)

RNG = random.Random(20260923)

MONSOON_MONTHS = {6, 7, 8, 9}

# Three 8-hour shifts anchored at midnight, so whatever hour the dashboard is
# opened at there is a shift genuinely in progress on the current calendar day.
SHIFTS = [
    (1, time(0, 0), time(8, 0)),
    (2, time(8, 0), time(16, 0)),
    (3, time(16, 0), time(0, 0)),
]
SHIFT_MINUTES = 480

# --- Master data -----------------------------------------------------------

MACHINES = [
    (Stage.BOARD_MANUFACTURING, "CORR-1", "Corrugator 1 (5-ply)", 250.0, "m/min"),
    (Stage.PRINTING, "PRINT-1", "Flexo Printer 1 (4-colour)", 6000.0, "sheets/hr"),
    (Stage.PRINTING, "PRINT-2", "Flexo Printer 2 (2-colour)", 4500.0, "sheets/hr"),
    (Stage.BUNDLING, "BUND-1", "Bundling Line 1", None, None),
]

DOWNTIME_CODES = [
    # (category, code, description, weight, typical minutes)
    (TimeCategory.SETUP, "CHG-ORDER", "Order changeover", 26, (8, 22)),
    (TimeCategory.SETUP, "CHG-PLATE", "Plate / ink change", 16, (10, 28)),
    (TimeCategory.SETUP, "PM-PLANNED", "Planned maintenance", 4, (30, 75)),
    (TimeCategory.BREAKDOWN, "BD-SPLICE", "Splice failure at reel stand", 13, (6, 26)),
    (TimeCategory.BREAKDOWN, "BD-GLUE", "Glue unit fault", 7, (12, 45)),
    (TimeCategory.BREAKDOWN, "BD-STEAM", "Steam pressure drop", 6, (15, 55)),
    (TimeCategory.BREAKDOWN, "BD-JAM", "Sheet jam in feeder", 9, (5, 18)),
    (TimeCategory.BREAKDOWN, "BD-ELEC", "Electrical / drive fault", 4, (20, 80)),
    (TimeCategory.WAITING, "WT-PAPER", "Waiting for paper reels", 6, (10, 40)),
    (TimeCategory.WAITING, "WT-UPSTREAM", "Waiting for upstream material", 9, (8, 35)),
    (TimeCategory.WAITING, "WT-POWER", "Power outage / DG changeover", 3, (10, 30)),
    (TimeCategory.IDLE, "ID-NOORDER", "No order scheduled", 3, (15, 60)),
    (TimeCategory.IDLE, "ID-BREAK", "Shift break", 4, (15, 30)),
]

DEFECT_CODES = [
    (Stage.BOARD_MANUFACTURING, "DEF-WARP", "Warp beyond tolerance", 28),
    (Stage.BOARD_MANUFACTURING, "DEF-DELAM", "Ply delamination", 18),
    (Stage.BOARD_MANUFACTURING, "DEF-MOIST", "Moisture out of band", 14),
    (Stage.BOARD_MANUFACTURING, "DEF-TRIM", "Trim / edge damage", 20),
    (Stage.BOARD_MANUFACTURING, "DEF-CRUSH", "Flute crush at stacker", 10),
    (Stage.PRINTING, "DEF-REG", "Print registration off", 30),
    (Stage.PRINTING, "DEF-SHADE", "Shade variation", 22),
    (Stage.PRINTING, "DEF-SMUDGE", "Smudge / scuff", 18),
    (Stage.PRINTING, "DEF-SETUP", "Setup waste sheets", 25),
    (Stage.BUNDLING, "DEF-COUNT", "Short count in bundle", 12),
    (Stage.BUNDLING, "DEF-STRAP", "Strapping failure", 8),
]

# Which stops can physically happen where. Without this the Paretos read
# nonsense - a glue unit fault on the bundling line - and a Pareto nobody
# believes is a Pareto nobody acts on.
CODES_BY_STAGE = {
    Stage.BOARD_MANUFACTURING: {
        "CHG-ORDER", "PM-PLANNED", "BD-SPLICE", "BD-GLUE", "BD-STEAM",
        "BD-ELEC", "WT-PAPER", "WT-POWER", "ID-NOORDER", "ID-BREAK",
    },
    Stage.PRINTING: {
        "CHG-ORDER", "CHG-PLATE", "PM-PLANNED", "BD-JAM", "BD-ELEC",
        "WT-UPSTREAM", "WT-POWER", "ID-NOORDER", "ID-BREAK",
    },
    Stage.BUNDLING: {
        "PM-PLANNED", "BD-JAM", "BD-ELEC", "WT-UPSTREAM", "WT-POWER",
        "ID-NOORDER", "ID-BREAK",
    },
}

CUSTOMERS = [
    "Agrawal Foods", "Kirloskar Pumps", "Sunrise Ceramics", "Vedant Pharma",
    "Deccan Textiles", "Patel Agro Exports", "Nandi Dairy", "Shakti Electricals",
    "Gokul Beverages", "Meridian Appliances",
]

SPECS = [
    # (ply, flute, gsm, bf, corrugator m/min, printer sheets/hr, sheet mm)
    # The printing standard falls with sheet size and ply, as it does in practice.
    ("3-ply", "B", 120.0, 18.0, 235.0, 5200.0, (1200, 800)),
    ("3-ply", "C", 140.0, 20.0, 215.0, 4600.0, (1400, 900)),
    ("5-ply", "BC", 150.0, 22.0, 175.0, 3400.0, (1600, 1100)),
    ("5-ply", "BC", 180.0, 24.0, 160.0, 2900.0, (1800, 1200)),
    ("3-ply", "E", 110.0, 16.0, 245.0, 5800.0, (900, 600)),
]

# Targets and control bands, as a plant would set them at onboarding: target is
# the best demonstrated sustained level, the red line sits below it, and the
# season-adjusted metrics carry a wider monsoon band.
TARGETS = {
    # code: (target, red_line, band_low, band_high, monsoon_low, monsoon_high)
    "overall_yield_pct": (88.0, 84.0, None, None, None, None),
    "plant_productivity_pct": (62.0, 52.0, None, None, None, None),
    # Per day. The dashboard multiplies this by the days in the selected range.
    "cost_of_waste_inr": (700000.0, 950000.0, None, None, None, None),
    "power_per_tonne_kwh": (78.0, 92.0, None, None, None, None),
    "paper_yield_pct": (92.0, 88.0, None, None, None, None),
    "production_weight": (48.0, 40.0, None, None, None, None),
    "average_running_speed": (185.0, 150.0, None, None, None, None),
    "first_pass_good_board_pct": (96.0, 92.0, None, None, None, None),
    "uptime_pct": (80.0, 68.0, None, None, None, None),
    "run_rate_efficiency_pct": (72.0, 58.0, None, None, None, None),
    "setups_count": (6.0, 11.0, None, None, None, None),
    "setups_avg_time": (16.0, 26.0, None, None, None, None),
    "first_pass_good_printed_pct": (97.0, 94.0, None, None, None, None),
    "conversion_waste_pct": (3.0, 6.0, None, None, None, None),
    "bundles_per_hour": (58.0, 44.0, None, None, None, None),
    "output_per_worker_shift": (520.0, 400.0, None, None, None, None),
    "count_accuracy_pct": (99.5, 98.5, None, None, None, None),
    "starvation_minutes": (25.0, 60.0, None, None, None, None),
    "roll_temperature": (168.0, 158.0, 162.0, 176.0, 164.0, 178.0),
    "steam_pressure": (12.0, 10.0, 10.5, 13.5, 11.0, 13.5),
    "glue_gap": (0.15, 0.25, 0.10, 0.22, 0.10, 0.20),
    "moisture_pct": (7.5, 9.5, 6.0, 8.5, 6.5, 9.5),
    "warp": (2.0, 5.0, 0.0, 4.0, 0.0, 6.0),
    # Ford cup No. 4 efflux time, and pH for water-based inks.
    "ink_viscosity": (22.0, 28.0, 18.0, 26.0, None, None),
    "ink_ph": (8.8, 9.6, 8.2, 9.4, None, None),
}


def _weighted_choice(options: list[tuple]) -> tuple:
    total = sum(option[3] for option in options)
    pick = RNG.uniform(0, total)
    running = 0.0
    for option in options:
        running += option[3]
        if pick <= running:
            return option
    return options[-1]


def reset(db: Session) -> None:
    """Truncates every fact and master table except the metric catalog, which is
    seeded by migration rather than by this script."""
    tables = [
        table.name
        for table in reversed(Base.metadata.sorted_tables)
        if table.name not in {"metric_definitions", "alembic_version"}
    ]
    db.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    db.commit()


def seed_master_data(db: Session) -> tuple[Plant, list[Machine], dict, dict]:
    plant = Plant(
        name="Shree Balaji Packaging - Unit 1",
        location="Bhiwandi, Maharashtra",
        line_type=LineType.AUTOMATIC,
    )
    db.add(plant)
    db.flush()

    machines = [
        Machine(
            plant_id=plant.id,
            stage=stage,
            machine_code=code,
            name=name,
            rated_speed=rated,
            rated_speed_unit=unit,
        )
        for stage, code, name, rated, unit in MACHINES
    ]
    db.add_all(machines)

    downtime_codes = {
        code: DowntimeReasonCode(category=category, code=code, description=description)
        for category, code, description, _weight, _minutes in DOWNTIME_CODES
    }
    db.add_all(downtime_codes.values())

    defect_codes = {
        code: DefectReasonCode(stage=stage, code=code, description=description)
        for stage, code, description, _weight in DEFECT_CODES
    }
    db.add_all(defect_codes.values())

    definitions = {definition.code: definition for definition in db.query(MetricDefinition).all()}
    effective_from = date.today() - timedelta(days=365)
    for metric_code, (target, red_line, low, high, monsoon_low, monsoon_high) in TARGETS.items():
        definition = definitions.get(metric_code)
        if definition is None:
            continue
        db.add(
            PlantMetricTarget(
                plant_id=plant.id,
                metric_definition_id=definition.id,
                target_value=target,
                red_line_value=red_line,
                band_low=low,
                band_high=high,
                monsoon_band_low=monsoon_low,
                monsoon_band_high=monsoon_high,
                effective_from=effective_from,
            )
        )

    db.flush()
    return plant, machines, downtime_codes, defect_codes


def _day_character(day: date) -> dict:
    """A day's underlying condition, which every machine on it then inherits.

    Real plants have good days and bad days for reasons that span machines -
    paper quality, humidity, who is on shift - so the simulation gives each day a
    character rather than rolling every number independently.
    """
    monsoon = day.month in MONSOON_MONTHS
    # A slow drift in condition plus occasional bad days, so trends have shape.
    base = 0.82 + 0.10 * RNG.random()
    if monsoon:
        base -= 0.06
    if RNG.random() < 0.12:
        base -= 0.13  # a genuinely bad day
    return {
        "monsoon": monsoon,
        "health": max(0.55, min(0.98, base)),
        "humid": monsoon and RNG.random() < 0.7,
    }


def _make_orders(db: Session, plant: Plant, day: date, count: int) -> list[Order]:
    orders = []
    for index in range(count):
        ply, flute, gsm, bf, standard, print_standard, (length, width) = RNG.choice(SPECS)
        order = Order(
            plant_id=plant.id,
            order_number=f"SO-{day.strftime('%y%m%d')}-{index + 1:02d}",
            customer_name=RNG.choice(CUSTOMERS),
            ply_construction=ply,
            flute_profile=flute,
            sheet_length_mm=float(length),
            sheet_width_mm=float(width),
            paper_gsm=gsm,
            paper_bf=bf,
            quantity_ordered=RNG.randrange(4000, 26000, 500),
            due_date=day + timedelta(days=RNG.randint(1, 4)),
            standard_speed=standard,
            standard_speed_unit="m/min",
            printing_standard_sheets_per_hr=print_standard,
        )
        orders.append(order)
    db.add_all(orders)
    db.flush()
    return orders


def _fill_shift_minutes(
    start: datetime,
    total_minutes: int,
    *,
    health: float,
    downtime_codes: dict,
    stage: Stage,
) -> list[tuple[TimeCategory, datetime, datetime, float, str | None]]:
    """Classifies every minute of a shift as running, setup, breakdown, waiting
    or idle - the spec's time accounting, with nothing unaccounted for."""
    segments: list[tuple[TimeCategory, datetime, datetime, float, str | None]] = []
    cursor = start
    remaining = total_minutes

    # Roughly how much of the shift is lost, driven by the day's health. Printing
    # loses more to changeovers than the corrugator does.
    loss_target = (1 - health) * total_minutes * (1.6 if stage is Stage.PRINTING else 1.0)
    lost = 0.0

    applicable = [entry for entry in DOWNTIME_CODES if entry[1] in CODES_BY_STAGE[stage]]

    while remaining > 0:
        # A stretch of running, then an interruption.
        run_minutes = min(remaining, RNG.randint(25, 95))
        if run_minutes > 0:
            end = cursor + timedelta(minutes=run_minutes)
            segments.append((TimeCategory.RUNNING, cursor, end, float(run_minutes), None))
            cursor = end
            remaining -= run_minutes

        if remaining <= 0:
            break

        if lost >= loss_target and remaining > 0:
            # Budget spent: the rest of the shift runs.
            end = cursor + timedelta(minutes=remaining)
            segments.append((TimeCategory.RUNNING, cursor, end, float(remaining), None))
            remaining = 0
            break

        category, code, _description, _weight, (low, high) = _weighted_choice(applicable)
        stop_minutes = min(remaining, RNG.randint(low, high))
        end = cursor + timedelta(minutes=stop_minutes)
        segments.append((category, cursor, end, float(stop_minutes), code))
        cursor = end
        remaining -= stop_minutes
        lost += stop_minutes

    return segments


def _seed_day(
    db: Session,
    plant: Plant,
    machines: list[Machine],
    downtime_codes: dict,
    defect_codes: dict,
    definitions: dict,
    day: date,
    *,
    now: datetime,
) -> None:
    character = _day_character(day)
    corrugator = next(m for m in machines if m.stage is Stage.BOARD_MANUFACTURING)
    printers = [m for m in machines if m.stage is Stage.PRINTING]
    bundler = next(m for m in machines if m.stage is Stage.BUNDLING)

    orders = _make_orders(db, plant, day, RNG.randint(4, 7))
    dg_minutes_today = 0.0

    for shift_number, start_time, end_time in SHIFTS:
        shift_start = datetime.combine(day, start_time)
        if shift_start > now:
            continue
        shift_end = shift_start + timedelta(minutes=SHIFT_MINUTES)
        # Today's current shift is only partly done - that is what gives the
        # status line a machine genuinely mid-run.
        elapsed = int(min(SHIFT_MINUTES, (now - shift_start).total_seconds() / 60))
        if elapsed < 20:
            continue

        shift = Shift(
            plant_id=plant.id,
            shift_date=day,
            shift_number=shift_number,
            start_time=shift_start,
            end_time=shift_end,
            scheduled_minutes=SHIFT_MINUTES,
        )
        db.add(shift)
        db.flush()

        shift_orders = RNG.sample(orders, k=min(len(orders), RNG.randint(2, 3)))
        board_kg_this_shift = 0.0
        printed_good_total = 0.0
        printing_lost_minutes = 0.0

        # --- Boarding -----------------------------------------------------
        corr_segments = _fill_shift_minutes(
            shift_start,
            elapsed,
            health=character["health"],
            downtime_codes=downtime_codes,
            stage=Stage.BOARD_MANUFACTURING,
        )
        corr_run = _build_run(
            db,
            corrugator,
            shift,
            shift_orders[0],
            shift_start,
            corr_segments,
            downtime_codes,
        )

        running_minutes = sum(s[3] for s in corr_segments if s[0] is TimeCategory.RUNNING)
        standard = shift_orders[0].standard_speed or 200.0
        actual_speed = standard * (0.68 + 0.30 * character["health"]) * RNG.uniform(0.94, 1.06)
        corr_run.lineal_metres = round(actual_speed * running_minutes, 1)

        # Mass balance: paper in, board out, the difference is boarding's waste.
        width_m = 1.6
        gsm = shift_orders[0].paper_gsm or 140.0
        plies = 5 if (shift_orders[0].ply_construction or "3-ply").startswith("5") else 3
        board_kg = corr_run.lineal_metres * width_m * gsm * plies / 1000
        boarding_waste = 0.055 + (0.03 if character["monsoon"] else 0.0) + RNG.uniform(0, 0.03)
        paper_kg = board_kg / (1 - boarding_waste)
        board_kg_this_shift = board_kg

        db.add_all(
            [
                MaterialFlow(
                    machine_run_id=corr_run.id,
                    material_type=MaterialType.KRAFT_PAPER,
                    input_qty=round(paper_kg, 1),
                    output_qty=round(board_kg, 1),
                    unit="kg",
                ),
                MaterialFlow(
                    machine_run_id=corr_run.id,
                    material_type=MaterialType.BOARD,
                    input_qty=round(paper_kg, 1),
                    output_qty=round(board_kg, 1),
                    unit="kg",
                ),
                MaterialFlow(
                    machine_run_id=corr_run.id,
                    material_type=MaterialType.STARCH,
                    input_qty=round(board_kg * 0.042, 2),
                    output_qty=round(board_kg * 0.042, 2),
                    unit="kg",
                ),
            ]
        )

        sheets_out = max(int(corr_run.lineal_metres / 1.3), 1)
        _add_quality(
            db,
            corr_run,
            total=sheets_out,
            good_fraction=0.93 + 0.055 * character["health"],
            unit="sheets",
            stage=Stage.BOARD_MANUFACTURING,
            defect_codes=defect_codes,
            monsoon=character["monsoon"],
        )
        _add_parameters(db, corrugator, corr_run, shift_start, elapsed, character, definitions)

        # --- Printing -----------------------------------------------------
        for index, printer in enumerate(printers):
            order = shift_orders[min(index, len(shift_orders) - 1)]
            segments = _fill_shift_minutes(
                shift_start,
                elapsed,
                health=character["health"] * RNG.uniform(0.92, 1.02),
                downtime_codes=downtime_codes,
                stage=Stage.PRINTING,
            )
            run = _build_run(db, printer, shift, order, shift_start, segments, downtime_codes)
            run_minutes = sum(s[3] for s in segments if s[0] is TimeCategory.RUNNING)
            printing_lost_minutes += sum(
                s[3] for s in segments if s[0] in (TimeCategory.BREAKDOWN, TimeCategory.SETUP)
            )

            # A printer rated at 6,000 sheets/hr delivers far less across a
            # shift, and it is judged against the job standard, not the nameplate.
            job_standard = order.printing_standard_sheets_per_hr or 4500.0
            sheets = int(job_standard * (run_minutes / 60) * RNG.uniform(0.78, 1.02))
            _add_quality(
                db,
                run,
                total=max(sheets, 1),
                good_fraction=0.955 + 0.03 * character["health"],
                unit="sheets",
                stage=Stage.PRINTING,
                defect_codes=defect_codes,
                monsoon=character["monsoon"],
            )
            printed_good_total += sheets
            db.add(
                MaterialFlow(
                    machine_run_id=run.id,
                    material_type=MaterialType.INK,
                    input_qty=round(sheets / 1000 * RNG.uniform(0.7, 1.4), 2),
                    output_qty=None,
                    unit="kg",
                )
            )
            _add_ink_checks(db, printer, run, shift_start, elapsed, definitions)

        # --- Bundling -----------------------------------------------------
        bundling_segments = _fill_shift_minutes(
            shift_start,
            elapsed,
            health=character["health"],
            downtime_codes=downtime_codes,
            stage=Stage.BUNDLING,
        )
        bundling_segments = _inject_starvation(
            bundling_segments, printing_lost_minutes, downtime_codes
        )
        bundling_run = _build_run(
            db, bundler, shift, shift_orders[-1], shift_start, bundling_segments, downtime_codes
        )
        bundling_running = sum(s[3] for s in bundling_segments if s[0] is TimeCategory.RUNNING)
        starvation = sum(s[3] for s in bundling_segments if s[0] is TimeCategory.WAITING)

        workers = RNG.randint(6, 10)
        bundles = int(bundling_running / 60 * RNG.uniform(48, 64))
        # Dispatched weight is board weight less what printing and bundling lost.
        dispatched_kg = board_kg_this_shift * RNG.uniform(0.93, 0.975)

        db.add(
            BundlingRecord(
                machine_run_id=bundling_run.id,
                worker_count=workers,
                bundles_count=max(bundles, 1),
                output_kg=round(dispatched_kg, 1),
                count_accuracy_pct=round(RNG.uniform(98.4, 99.9), 2),
                starvation_minutes=round(starvation, 1),
            )
        )
        _add_quality(
            db,
            bundling_run,
            total=max(bundles, 1),
            good_fraction=0.99,
            unit="bundles",
            stage=Stage.BUNDLING,
            defect_codes=defect_codes,
            monsoon=character["monsoon"],
        )

        # Orders staged for dispatch, which is what on-time delivery reads from.
        # Nearly everything ships: a plant that left a fifth of its orders open
        # for weeks would have no customers, and the stale rows would crowd out
        # every actionable alert on the Level 1 panel.
        for order in shift_orders:
            if order.order_complete_staged_at is None and RNG.random() < 0.8:
                order.order_complete_staged_at = shift_start + timedelta(
                    minutes=RNG.randint(240, 470)
                )

        # --- Energy -------------------------------------------------------
        tonnes = board_kg_this_shift / 1000
        shift_kwh = tonnes * RNG.uniform(70, 92) if tonnes else RNG.uniform(400, 700)
        # The genset runs when the grid drops - the fact an owner reacts to.
        dg_fraction = 0.28 if any(s[4] == "WT-POWER" for s in corr_segments) else RNG.uniform(0, 0.1)
        dg_kwh = shift_kwh * dg_fraction
        dg_minutes_today += dg_kwh
        db.add_all(
            [
                PowerReading(
                    plant_id=plant.id,
                    source=PowerSource.GRID,
                    kwh=round(shift_kwh - dg_kwh, 1),
                    recorded_at=shift_start + timedelta(minutes=elapsed - 1),
                ),
                PowerReading(
                    plant_id=plant.id,
                    source=PowerSource.DG,
                    kwh=round(dg_kwh, 1),
                    recorded_at=shift_start + timedelta(minutes=elapsed - 1),
                ),
            ]
        )

    db.flush()


def _build_run(
    db: Session,
    machine: Machine,
    shift: Shift,
    order: Order,
    shift_start: datetime,
    segments: list[tuple],
    downtime_codes: dict,
) -> MachineRun:
    run = MachineRun(
        machine_id=machine.id,
        shift_id=shift.id,
        order_id=order.id,
        start_time=shift_start,
        end_time=segments[-1][2] if segments else None,
    )
    db.add(run)
    db.flush()

    db.add_all(
        [
            TimeLog(
                machine_run_id=run.id,
                category=category,
                reason_code_id=(downtime_codes[code].id if code else None),
                start_time=start,
                end_time=end,
                duration_minutes=minutes,
            )
            for category, start, end, minutes, code in segments
        ]
    )
    return run


def _inject_starvation(
    segments: list[tuple], printing_lost_minutes: float, downtime_codes: dict
) -> list[tuple]:
    """Turns some of bundling's idle time into explicit waiting-on-upstream time,
    proportional to what printing actually lost.

    Starvation is recorded at bundling but attributable to upstream performance,
    and Level 3 links each event back to the stop that caused it - which only
    works if the two actually overlap in time.
    """
    if printing_lost_minutes <= 0:
        return segments
    converted: list[tuple] = []
    budget = printing_lost_minutes * 0.45
    for category, start, end, minutes, code in segments:
        if category is TimeCategory.IDLE and budget > 0:
            converted.append(
                (TimeCategory.WAITING, start, end, minutes, "WT-UPSTREAM")
            )
            budget -= minutes
        else:
            converted.append((category, start, end, minutes, code))
    return converted


def _add_quality(
    db: Session,
    run: MachineRun,
    *,
    total: int,
    good_fraction: float,
    unit: str,
    stage: Stage,
    defect_codes: dict,
    monsoon: bool,
) -> None:
    good_fraction = max(0.85, min(0.995, good_fraction))
    good = int(total * good_fraction)
    reject = max(total - good, 0)

    record = QualityRecord(
        machine_run_id=run.id, good_qty=float(good), reject_qty=float(reject), unit=unit
    )
    db.add(record)
    db.flush()

    if reject <= 0:
        return

    candidates = [entry for entry in DEFECT_CODES if entry[0] is stage]
    if not candidates:
        return

    # Monsoon pushes rejects towards moisture and warp rather than spreading them
    # evenly - which is what makes the seasonal Pareto look different.
    weights = [
        weight * (2.2 if monsoon and code in {"DEF-MOIST", "DEF-WARP"} else 1.0)
        for _stage, code, _description, weight in candidates
    ]
    remaining = reject
    for index, (_stage, code, _description, _weight) in enumerate(candidates):
        if remaining <= 0:
            break
        share = weights[index] / sum(weights)
        quantity = int(reject * share * RNG.uniform(0.6, 1.4))
        quantity = min(quantity, remaining)
        if quantity <= 0:
            continue
        db.add(
            DefectObservation(
                quality_record_id=record.id,
                reason_code_id=defect_codes[code].id,
                quantity=float(quantity),
            )
        )
        remaining -= quantity


def _add_parameters(
    db: Session,
    machine: Machine,
    run: MachineRun,
    shift_start: datetime,
    elapsed: int,
    character: dict,
    definitions: dict,
) -> None:
    """The early-warning layer: roll temperature, steam pressure, glue gap, plus
    QA sampling for moisture and warp.

    Roll temperature is given a slow downward drift on some shifts, because a
    drift in roll temperature precedes warp and delamination by a significant
    interval - which is exactly what the drift alert is for.
    """
    drifting = RNG.random() < 0.25
    readings_every = 15

    base_temp = RNG.uniform(166, 172)
    base_steam = RNG.uniform(11.4, 12.8)
    base_gap = RNG.uniform(0.13, 0.18)

    for minute in range(0, elapsed, readings_every):
        at = shift_start + timedelta(minutes=minute)
        progress = minute / max(elapsed, 1)

        temp = base_temp + RNG.uniform(-1.2, 1.2)
        if drifting:
            temp -= 11 * progress  # walks out of the 162-176 band by shift end
        steam = base_steam + RNG.uniform(-0.4, 0.4) - (0.9 * progress if drifting else 0)
        gap = base_gap + RNG.uniform(-0.01, 0.01)

        for code, value in (
            ("roll_temperature", temp),
            ("steam_pressure", steam),
            ("glue_gap", gap),
        ):
            definition = definitions.get(code)
            if definition is None:
                continue
            db.add(
                ParameterReading(
                    machine_id=machine.id,
                    machine_run_id=run.id,
                    metric_definition_id=definition.id,
                    source=ParameterSource.PLC_LIVE,
                    value=round(value, 3),
                    recorded_at=at,
                )
            )

    # QA sampling per order: moisture and warp, worse in the monsoon.
    for code, base, spread in (("moisture_pct", 7.2, 0.8), ("warp", 1.8, 1.0)):
        definition = definitions.get(code)
        if definition is None:
            continue
        value = base + RNG.uniform(-spread, spread) + (1.4 if character["humid"] else 0)
        db.add(
            ParameterReading(
                machine_id=machine.id,
                machine_run_id=run.id,
                metric_definition_id=definition.id,
                source=ParameterSource.QA_SAMPLE,
                value=round(value, 2),
                recorded_at=shift_start + timedelta(minutes=min(elapsed - 1, RNG.randint(60, 400))),
            )
        )


def _add_ink_checks(
    db: Session,
    machine: Machine,
    run: MachineRun,
    shift_start: datetime,
    elapsed: int,
    definitions: dict,
) -> None:
    """Printing's parameter panel is the ink check log: viscosity by Ford cup
    No. 4 and pH, each check timestamped so an overdue check is itself a finding.

    Checks are spaced two to three hours apart and occasionally skipped, which is
    what gives the overdue flag something to catch.
    """
    checks = [
        ("ink_viscosity", lambda: RNG.uniform(19.5, 25.5)),
        ("ink_ph", lambda: RNG.uniform(8.4, 9.3)),
        ("caliper_retention_pct", lambda: RNG.uniform(88, 97)),
    ]
    for minute in range(40, elapsed, RNG.choice([130, 160, 190])):
        if RNG.random() < 0.12:
            continue  # a check that nobody took
        for code, value_fn in checks:
            definition = definitions.get(code)
            if definition is None:
                continue
            db.add(
                ParameterReading(
                    machine_id=machine.id,
                    machine_run_id=run.id,
                    metric_definition_id=definition.id,
                    source=ParameterSource.QA_SAMPLE,
                    value=round(value_fn(), 2),
                    recorded_at=shift_start + timedelta(minutes=minute),
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60, help="days of history ending today")
    parser.add_argument("--reset", action="store_true", help="truncate existing data first")
    args = parser.parse_args()

    Base.metadata.create_all(engine)
    now = datetime.now()

    with SessionLocal() as db:
        if args.reset:
            reset(db)

        plant, machines, downtime_codes, defect_codes = seed_master_data(db)
        definitions = {definition.code: definition for definition in db.query(MetricDefinition).all()}

        start = now.date() - timedelta(days=args.days - 1)
        for offset in range(args.days):
            day = start + timedelta(days=offset)
            _seed_day(
                db,
                plant,
                machines,
                downtime_codes,
                defect_codes,
                definitions,
                day,
                now=now,
            )
            if offset % 10 == 0:
                db.commit()
                print(f"  seeded through {day}")

        # Anything due more than a few days ago has shipped by now, late or not.
        # Leaving a month of orders permanently open would misreport on-time
        # delivery and leave a backlog of stale rows behind every query.
        cutoff = now.date() - timedelta(days=3)
        shipped_late = 0
        for order in (
            db.query(Order)
            .filter(
                Order.plant_id == plant.id,
                Order.order_complete_staged_at.is_(None),
                Order.due_date < cutoff,
            )
            .all()
        ):
            # Most ship on time; a realistic minority ship a day or two late.
            slip = RNG.choice([0, 0, 0, 0, 1, 1, 2])
            order.order_complete_staged_at = datetime.combine(
                order.due_date + timedelta(days=slip), time(RNG.randint(9, 21), RNG.randint(0, 59))
            )
            shipped_late += 1 if slip else 0

        db.commit()
        print(
            f"Seeded plant {plant.id} ({plant.name}) with {args.days} days ending {now.date()}."
        )
        print(f"  {shipped_late} historical orders shipped late.")


if __name__ == "__main__":
    main()
