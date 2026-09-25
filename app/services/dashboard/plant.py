"""Level 1 - the plant view.

Answers one question for one audience: "what is happening with the plant right
now?", for the owner and the GM. The restraint is the feature - four rollup
cards, never five; exactly two charts; no machine names, no operating parameters,
no tables, no Paretos. All of that lives one level down.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Machine, MachineRun, Shift
from app.models.enums import MaterialType, Stage
from app.services.dashboard import facts
from app.services.dashboard.bands import (
    Band,
    delta_direction,
    load_bands,
    rag_for,
    scale_for_days,
)
from app.services.dashboard.ranges import Granularity, RangeSpec
from app.services.dashboard.status import stage_status_line

# The three stages, always in process-flow order: the top of every screen mirrors
# the plant, so a plant person recognises it without training.
STAGE_ORDER = [Stage.BOARD_MANUFACTURING, Stage.PRINTING, Stage.BUNDLING]


def _ratio(numerator: float | None, denominator: float | None, scale: float = 100.0) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(scale * numerator / denominator, 2)


def range_totals(
    db: Session, plant_id: int, start: date, end: date, *, as_of: datetime | None = None
) -> dict:
    """The raw ingredients of the four rollups, summed over a date window.

    Utilisation, rate efficiency and quality are corrugator-scoped; yield, waste
    and power are plant-wide.
    """
    corrugator = Stage.BOARD_MANUFACTURING

    time_split = facts.time_split_by_day(db, plant_id, start, end, corrugator, as_of=as_of)
    scheduled = facts.scheduled_minutes_by_day(db, plant_id, start, end, corrugator, as_of=as_of)
    quality = facts.quality_by_day(db, plant_id, start, end, corrugator)
    rate = facts.rate_efficiency_by_day(db, plant_id, start, end, corrugator)
    paper = facts.material_by_day(
        db, plant_id, start, end, stage=corrugator, material_type=MaterialType.KRAFT_PAPER
    )
    board = facts.material_by_day(
        db, plant_id, start, end, stage=corrugator, material_type=MaterialType.BOARD
    )
    dispatched = facts.dispatched_kg_by_day(db, plant_id, start, end)
    power = facts.power_by_day(db, plant_id, start, end)

    running_minutes = sum(split.get("running", 0.0) for split in time_split.values())
    scheduled_minutes = sum(scheduled.values())
    good_qty = sum(good for good, _ in quality.values())
    reject_qty = sum(reject for _, reject in quality.values())
    rate_weighted = sum(weighted for weighted, _ in rate.values())
    rate_weight = sum(weight for _, weight in rate.values())
    paper_in = sum(inp for inp, _ in paper.values())
    board_out = sum(out for _, out in board.values())
    dispatched_kg = sum(dispatched.values())
    grid_kwh = sum(day["grid_kwh"] for day in power.values())
    dg_kwh = sum(day["dg_kwh"] for day in power.values())

    # Linear metres run on the corrugator - the instrument-cluster odometer's
    # other figure, alongside tonnes. Metres-run and board-output measure the
    # same running time from two ends (encoder length vs weighed output), so
    # this is its own query rather than derived from board_out.
    lineal_metres = (
        db.query(func.coalesce(func.sum(MachineRun.lineal_metres), 0.0))
        .join(Machine, Machine.id == MachineRun.machine_id)
        .join(Shift, Shift.id == MachineRun.shift_id)
        .filter(
            Shift.plant_id == plant_id,
            Shift.shift_date >= start,
            Shift.shift_date <= end,
            Machine.stage == corrugator,
        )
        .scalar()
    ) or 0.0

    minutes_by_category: dict[str, float] = defaultdict(float)
    for split in time_split.values():
        for category, minutes in split.items():
            minutes_by_category[category] += minutes

    utilisation = _ratio(running_minutes, scheduled_minutes)
    rate_efficiency = round(rate_weighted / rate_weight, 2) if rate_weight else None
    quality_pct = _ratio(good_qty, good_qty + reject_qty)
    productivity = (
        round(utilisation * rate_efficiency * quality_pct / 10000, 2)
        if None not in (utilisation, rate_efficiency, quality_pct)
        else None
    )

    # Waste is the paper that never left as saleable board. Paper is 60-65% of
    # the cost of a box, so this is the number an owner feels in their stomach.
    waste_kg = max(paper_in - dispatched_kg, 0.0) if paper_in else 0.0
    planned_waste_kg = paper_in * settings.planned_waste_pct / 100 if paper_in else 0.0
    total_kwh = grid_kwh + dg_kwh
    tonnes = board_out / 1000

    waste_cost = None
    excess_waste_cost = None
    if paper_in:
        # waste kg x paper rate + starch + power share, per the spec's formula.
        starch_share = waste_kg * settings.starch_rate_inr_per_kg * settings.starch_share_of_board
        power_share = (total_kwh * settings.power_rate_inr_per_kwh) * (
            waste_kg / paper_in if paper_in else 0
        )
        waste_cost = round(waste_kg * settings.paper_rate_inr_per_kg + starch_share + power_share, 0)
        planned_cost = round(planned_waste_kg * settings.paper_rate_inr_per_kg, 0)
        # The alert is on the excess, not the total: some waste is planned.
        excess_waste_cost = round(max(waste_cost - planned_cost, 0.0), 0)

    return {
        "running_minutes": running_minutes,
        "scheduled_minutes": scheduled_minutes,
        "minutes_by_category": dict(minutes_by_category),
        "utilisation_pct": utilisation,
        "rate_efficiency_pct": rate_efficiency,
        "quality_pct": quality_pct,
        "plant_productivity_pct": productivity,
        "paper_consumed_kg": round(paper_in, 1),
        "board_output_kg": round(board_out, 1),
        "dispatched_kg": round(dispatched_kg, 1),
        "overall_yield_pct": _ratio(dispatched_kg, paper_in),
        "waste_kg": round(waste_kg, 1),
        "planned_waste_kg": round(planned_waste_kg, 1),
        "waste_cost_inr": waste_cost,
        "excess_waste_cost_inr": excess_waste_cost,
        "grid_kwh": round(grid_kwh, 1),
        "dg_kwh": round(dg_kwh, 1),
        "total_kwh": round(total_kwh, 1),
        "tonnes_produced": round(tonnes, 3),
        "lineal_metres_run": round(lineal_metres, 0),
        "power_per_tonne_kwh": _ratio(total_kwh, tonnes, scale=1.0),
        "dg_hours": round(dg_kwh / settings.dg_kw_rating, 1) if dg_kwh else 0.0,
        "grid_share_pct": _ratio(grid_kwh, total_kwh),
    }


def _card(
    key: str,
    label: str,
    value: float | None,
    unit: str,
    band: Band | None,
    *,
    previous: float | None = None,
    provisional: bool = False,
    sub_label: str | None = None,
    sub_values: list[dict] | None = None,
) -> dict:
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
        "previous": previous,
        "delta": (
            round(value - previous, 2) if value is not None and previous is not None else None
        ),
        "delta_direction": delta_direction(value, previous, band),
        "sub_label": sub_label,
        "sub_values": sub_values or [],
    }


def rollup_cards(
    db: Session,
    plant_id: int,
    spec: RangeSpec,
    bands: dict[str, Band],
    *,
    now: datetime,
) -> list[dict]:
    """Exactly four, never five."""
    current = range_totals(db, plant_id, spec.start, spec.end, as_of=now)
    previous: dict = {}
    if spec.prev_start and spec.prev_end:
        # The comparison window is fully elapsed, so it needs no as_of clamp.
        previous = range_totals(db, plant_id, spec.prev_start, spec.prev_end)

    provisional = spec.includes_today
    # Rupee totals accumulate with the range, so their band has to as well.
    days = spec.days

    return [
        _card(
            "overall_yield_pct",
            "Overall yield",
            current["overall_yield_pct"],
            "%",
            bands.get("overall_yield_pct"),
            previous=previous.get("overall_yield_pct"),
            provisional=provisional,
            sub_label="dispatched / paper consumed",
            sub_values=[
                {"label": "Dispatched", "value": current["dispatched_kg"], "unit": "kg"},
                {"label": "Paper in", "value": current["paper_consumed_kg"], "unit": "kg"},
            ],
        ),
        _card(
            "plant_productivity_pct",
            "Plant productivity",
            current["plant_productivity_pct"],
            "%",
            bands.get("plant_productivity_pct"),
            previous=previous.get("plant_productivity_pct"),
            provisional=provisional,
            # The three factors ride small beneath the composite, so the weak
            # lever is visible before anyone drills.
            sub_label="U x R x Q, corrugator",
            sub_values=[
                {"label": "U", "value": current["utilisation_pct"], "unit": "%"},
                {"label": "R", "value": current["rate_efficiency_pct"], "unit": "%"},
                {"label": "Q", "value": current["quality_pct"], "unit": "%"},
            ],
        ),
        _card(
            "cost_of_waste_inr",
            "Cost of waste",
            current["waste_cost_inr"],
            "INR",
            scale_for_days(bands.get("cost_of_waste_inr"), days),
            previous=previous.get("waste_cost_inr"),
            provisional=provisional,
            sub_label="excess over planned waste",
            sub_values=[
                {"label": "Excess", "value": current["excess_waste_cost_inr"], "unit": "INR"},
                {"label": "Waste", "value": current["waste_kg"], "unit": "kg"},
            ],
        ),
        _card(
            "power_per_tonne_kwh",
            "Power per tonne",
            current["power_per_tonne_kwh"],
            "kWh/t",
            bands.get("power_per_tonne_kwh"),
            previous=previous.get("power_per_tonne_kwh"),
            provisional=provisional,
            # Diesel generation gets equal billing: it is the most actionable
            # energy fact of the day.
            sub_label=f"DG {current['dg_hours']} hrs",
            sub_values=[
                {"label": "DG", "value": current["dg_hours"], "unit": "hrs"},
                {"label": "Grid share", "value": current["grid_share_pct"], "unit": "%"},
            ],
        ),
    ]


def flight_path(
    db: Session,
    plant_id: int,
    spec: RangeSpec,
    target_tonnes_per_shift: float | None,
    *,
    now: datetime,
) -> dict:
    """Will we make the period? Cumulative actual against the plan line, with the
    gap annotated in days - which converts a quantity into a decision."""
    actual_by_day = facts.board_output_tonnes_by_day(db, plant_id, spec.start, spec.end)
    plan_by_day = facts.planned_tonnes_by_day(
        db, plant_id, spec.start, spec.end, target_tonnes_per_shift, as_of=now
    )

    points: list[dict] = []
    actual_cum = 0.0
    plan_cum = 0.0

    if spec.granularity is Granularity.HOURLY:
        # Today: the day's cumulative against the day's plan, spread across the
        # hours that were actually rostered.
        hours = facts.hourly_breakdown(db, plant_id, spec.start, Stage.BOARD_MANUFACTURING)
        day_plan = plan_by_day.get(spec.start, 0.0)
        day_actual = actual_by_day.get(spec.start, 0.0)
        total_metres = sum(hour["lineal_metres"] for hour in hours) or 1.0
        plan_per_hour = day_plan / len(hours) if hours else 0.0
        for hour in hours:
            actual_cum += day_actual * (hour["lineal_metres"] / total_metres)
            plan_cum += plan_per_hour
            points.append(
                {
                    "bucket": f"{hour['hour']:02d}:00",
                    "actual_cumulative": round(actual_cum, 2),
                    "plan_cumulative": round(plan_cum, 2),
                }
            )
    else:
        day = spec.start
        while day <= spec.end:
            actual_cum += actual_by_day.get(day, 0.0)
            plan_cum += plan_by_day.get(day, 0.0)
            points.append(
                {
                    "bucket": day.isoformat(),
                    "actual_cumulative": round(actual_cum, 2),
                    "plan_cumulative": round(plan_cum, 2),
                }
            )
            day += timedelta(days=1)

    elapsed_days = max(len([d for d in plan_by_day if d <= spec.end]), 1)
    plan_per_day = plan_cum / elapsed_days if plan_cum else 0.0
    gap_tonnes = round(actual_cum - plan_cum, 2)
    gap_days = round(gap_tonnes / plan_per_day, 1) if plan_per_day else None

    return {
        "unit": "t",
        "points": points,
        "actual_total": round(actual_cum, 2),
        "plan_total": round(plan_cum, 2),
        "gap_tonnes": gap_tonnes,
        "gap_days": gap_days,
        "plan_available": bool(plan_by_day),
    }


def loss_waterfall(totals: dict) -> list[dict]:
    """Where did potential go? 100% -> minus not-running -> minus ran-slow ->
    minus rejected -> delivered. The productivity card expanded into a picture:
    three named, sized, ownable losses."""
    utilisation = totals["utilisation_pct"]
    rate = totals["rate_efficiency_pct"]
    quality = totals["quality_pct"]
    if None in (utilisation, rate, quality):
        return []

    not_running = round(100 - utilisation, 2)
    ran_slow = round(utilisation * (100 - rate) / 100, 2)
    rejected = round(utilisation * rate * (100 - quality) / 10000, 2)
    delivered = round(utilisation * rate * quality / 10000, 2)

    minutes = totals["minutes_by_category"]
    non_running_minutes = sum(v for k, v in minutes.items() if k != "running") or 1.0

    return [
        {"key": "potential", "label": "Potential", "value": 100.0, "kind": "total"},
        {
            "key": "not_running",
            "label": "Not running",
            "value": -not_running,
            "kind": "loss",
            "owner": "Maintenance & planning",
            "detail": {
                category: round(mins, 0)
                for category, mins in minutes.items()
                if category != "running"
            },
            "share_of_downtime": {
                category: round(100 * mins / non_running_minutes, 1)
                for category, mins in minutes.items()
                if category != "running"
            },
        },
        {
            "key": "ran_slow",
            "label": "Ran slow",
            "value": -ran_slow,
            "kind": "loss",
            "owner": "Production",
            "detail": {"rate_efficiency_pct": rate},
        },
        {
            "key": "rejected",
            "label": "Rejected",
            "value": -rejected,
            "kind": "loss",
            "owner": "Quality",
            "detail": {"quality_pct": quality},
        },
        {"key": "delivered", "label": "Delivered", "value": delivered, "kind": "total"},
    ]


def trend_series(
    db: Session, plant_id: int, end: date, days: int = 30, *, as_of: datetime | None = None
) -> dict:
    """30-day lines for the four rollups with target bands. Monsoon days are
    marked so a seasonal dip reads as expected rather than as failure."""
    from app.services.dashboard.ranges import MONSOON_MONTHS

    start = end - timedelta(days=days - 1)

    time_split = facts.time_split_by_day(
        db, plant_id, start, end, Stage.BOARD_MANUFACTURING, as_of=as_of
    )
    scheduled = facts.scheduled_minutes_by_day(
        db, plant_id, start, end, Stage.BOARD_MANUFACTURING, as_of=as_of
    )
    quality = facts.quality_by_day(db, plant_id, start, end, Stage.BOARD_MANUFACTURING)
    rate = facts.rate_efficiency_by_day(db, plant_id, start, end)
    paper = facts.material_by_day(
        db, plant_id, start, end, stage=Stage.BOARD_MANUFACTURING, material_type=MaterialType.KRAFT_PAPER
    )
    board = facts.material_by_day(
        db, plant_id, start, end, stage=Stage.BOARD_MANUFACTURING, material_type=MaterialType.BOARD
    )
    dispatched = facts.dispatched_kg_by_day(db, plant_id, start, end)
    power = facts.power_by_day(db, plant_id, start, end)

    points: list[dict] = []
    day = start
    while day <= end:
        paper_in = paper.get(day, (0.0, 0.0))[0]
        board_out = board.get(day, (0.0, 0.0))[1]
        dispatched_kg = dispatched.get(day, 0.0)
        good, reject = quality.get(day, (0.0, 0.0))
        weighted, weight = rate.get(day, (0.0, 0.0))
        running = time_split.get(day, {}).get("running", 0.0)
        scheduled_minutes = scheduled.get(day, 0.0)
        day_power = power.get(day, {"grid_kwh": 0.0, "dg_kwh": 0.0})
        total_kwh = day_power["grid_kwh"] + day_power["dg_kwh"]

        utilisation = _ratio(running, scheduled_minutes)
        rate_eff = round(weighted / weight, 2) if weight else None
        quality_pct = _ratio(good, good + reject)
        productivity = (
            round(utilisation * rate_eff * quality_pct / 10000, 2)
            if None not in (utilisation, rate_eff, quality_pct)
            else None
        )
        waste_kg = max(paper_in - dispatched_kg, 0.0)

        points.append(
            {
                "date": day.isoformat(),
                "overall_yield_pct": _ratio(dispatched_kg, paper_in),
                "plant_productivity_pct": productivity,
                "cost_of_waste_inr": (
                    round(waste_kg * settings.paper_rate_inr_per_kg, 0) if paper_in else None
                ),
                "power_per_tonne_kwh": _ratio(total_kwh, board_out / 1000, scale=1.0),
                "is_monsoon": day.month in MONSOON_MONTHS,
            }
        )
        day += timedelta(days=1)

    return {"days": days, "points": points}


def plant_overview(
    db: Session,
    plant_id: int,
    spec: RangeSpec,
    *,
    now: datetime,
) -> dict:
    bands = load_bands(db, plant_id, on_date=spec.end)
    target_tonnes = bands["production_weight"].target if "production_weight" in bands else None
    totals = range_totals(db, plant_id, spec.start, spec.end, as_of=now)

    return {
        "plant_id": plant_id,
        "generated_at": now,
        "range": {
            "mode": spec.mode.value,
            "start": spec.start,
            "end": spec.end,
            "label": spec.label,
            "granularity": spec.granularity.value,
            "provisional": spec.includes_today,
            "comparison_start": spec.prev_start,
            "comparison_end": spec.prev_end,
            # Custom hides deltas by default; the UI offers them as an opt-in.
            "comparison_default_visible": spec.mode.value != "custom",
        },
        # The status line never switches with the selector - it always shows the
        # plant right now.
        "status_line": stage_status_line(db, plant_id, now=now),
        "rollups": rollup_cards(db, plant_id, spec, bands, now=now),
        "flight_path": flight_path(db, plant_id, spec, target_tonnes, now=now),
        "waterfall": loss_waterfall(totals),
        "totals": totals,
    }
