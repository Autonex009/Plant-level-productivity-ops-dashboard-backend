"""Tests for the dashboard read API.

These cover the rules that are easy to get quietly wrong and expensive to get
wrong in front of a plant owner: the comparison-fairness rule, the utilisation
denominator on an in-progress shift, the two different throughput standards for
one job, and the promise that a dead data feed is never drawn as a dead machine.
"""

from datetime import date, datetime, timedelta

import pytest

from app.services.dashboard.bands import Band, rag_for, scale_for_days
from app.services.dashboard.ranges import Granularity, RangeMode, resolve_range

BASE = "/api/v1/dashboard/plants"


# --- Time ranges -----------------------------------------------------------


def test_month_compares_against_the_same_days_of_last_month():
    """A part-period is only ever compared with the same days of the prior
    period - Sep 1-21 versus Aug 1-21, never against a full August."""
    spec = resolve_range(RangeMode.MONTH, today=date(2026, 9, 21))

    assert (spec.start, spec.end) == (date(2026, 9, 1), date(2026, 9, 21))
    assert (spec.prev_start, spec.prev_end) == (date(2026, 8, 1), date(2026, 8, 21))


def test_month_comparison_clamps_to_a_shorter_prior_month():
    """31 March has no counterpart in February; the comparison lands on the 28th
    rather than overflowing into March."""
    spec = resolve_range(RangeMode.MONTH, today=date(2026, 3, 31))

    assert spec.prev_end == date(2026, 2, 28)


def test_week_is_calendar_week_to_date_not_a_rolling_seven_days():
    spec = resolve_range(RangeMode.WEEK, today=date(2026, 9, 23))  # a Wednesday

    assert spec.start == date(2026, 9, 21)  # Monday
    assert spec.days == 3


def test_ranges_that_include_today_are_provisional():
    assert resolve_range(RangeMode.TODAY, today=date(2026, 9, 23)).includes_today
    past = resolve_range(
        RangeMode.CUSTOM,
        today=date(2026, 9, 23),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 8, 31),
    )
    assert not past.includes_today


def test_long_custom_ranges_switch_to_weekly_granularity():
    """Daily rows stay readable to about a month; beyond that they become weekly."""
    short = resolve_range(
        RangeMode.CUSTOM, today=date(2026, 9, 23), date_from=date(2026, 9, 1), date_to=date(2026, 9, 20)
    )
    long = resolve_range(
        RangeMode.CUSTOM, today=date(2026, 9, 23), date_from=date(2026, 6, 1), date_to=date(2026, 8, 31)
    )

    assert short.granularity is Granularity.DAILY
    assert long.granularity is Granularity.WEEKLY


def test_custom_range_requires_both_bounds():
    with pytest.raises(ValueError):
        resolve_range(RangeMode.CUSTOM, today=date(2026, 9, 23), date_from=date(2026, 9, 1))


# --- RAG bands -------------------------------------------------------------


def test_rag_respects_direction_of_good():
    higher = Band("overall_yield_pct", "%", "Yield", 88.0, 84.0, None, None, False, False)
    lower = Band("cost_of_waste_inr", "INR", "Waste", 50_000.0, 70_000.0, None, None, True, False)

    assert [rag_for(v, higher) for v in (90, 86, 80)] == ["green", "amber", "red"]
    assert [rag_for(v, lower) for v in (40_000, 60_000, 90_000)] == ["green", "amber", "red"]


def test_a_missing_value_is_grey_not_red():
    """Grey means we cannot judge. A failed feed must never be reported as a
    failure of the thing being measured."""
    band = Band("uptime_pct", "%", "Uptime", 80.0, 68.0, None, None, False, False)

    assert rag_for(None, band) == "grey"
    assert rag_for(75.0, None) == "grey"


def test_cumulative_targets_scale_with_the_range_but_rates_do_not():
    """A rupee total accumulates over a month; a percentage does not."""
    money = Band("cost_of_waste_inr", "INR", "Waste", 700_000.0, 950_000.0, None, None, True, False)
    rate = Band("uptime_pct", "%", "Uptime", 80.0, 68.0, None, None, False, False)

    assert scale_for_days(money, 30).target == pytest.approx(21_000_000.0)
    assert scale_for_days(rate, 30).target == pytest.approx(80.0)


# --- Endpoints -------------------------------------------------------------


@pytest.fixture()
def dashboard_plant(client, plant, machine_corrugator, machine_printer, machine_bundler):
    return plant


def test_overview_returns_exactly_four_rollups_and_two_charts(client, dashboard_plant):
    response = client.get(f"{BASE}/{dashboard_plant['id']}/overview", params={"range": "today"})
    assert response.status_code == 200, response.text
    body = response.json()

    # Exactly four, never five - the restraint is the feature.
    assert len(body["rollups"]) == 4
    assert [card["key"] for card in body["rollups"]] == [
        "overall_yield_pct",
        "plant_productivity_pct",
        "cost_of_waste_inr",
        "power_per_tonne_kwh",
    ]
    assert len(body["status_line"]) == 3
    assert "flight_path" in body and "waterfall" in body


def test_overview_404s_for_an_unknown_plant(client):
    assert client.get(f"{BASE}/999/overview").status_code == 404


def test_a_machine_with_no_data_is_grey_not_down(client, dashboard_plant):
    """A failed data feed must not be reported as a failed machine."""
    response = client.get(f"{BASE}/{dashboard_plant['id']}/overview", params={"range": "today"})
    statuses = {row["stage"]: row["status"] for row in response.json()["status_line"]}

    # Nothing has been logged for these machines at all.
    assert set(statuses.values()) == {"no_data"}


def test_alerts_panel_becomes_recurring_issues_in_aggregate_modes(client, dashboard_plant):
    today = client.get(f"{BASE}/{dashboard_plant['id']}/overview", params={"range": "today"})
    month = client.get(f"{BASE}/{dashboard_plant['id']}/overview", params={"range": "month"})

    assert today.json()["alerts_panel_mode"] == "live"
    assert month.json()["alerts_panel_mode"] == "recurring"


def test_stage_view_caps_kpi_cards_at_five(client, dashboard_plant):
    for stage in ("board_manufacturing", "printing", "bundling"):
        response = client.get(f"{BASE}/{dashboard_plant['id']}/stages/{stage}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["kpis"]) <= 5
        assert set(body["charts"]) == {"primary", "secondary"}


def test_bundling_has_no_parameters_panel(client, dashboard_plant):
    """Bundling has no operating parameters; its panel is the worker and audit
    log instead."""
    stage_view = client.get(f"{BASE}/{dashboard_plant['id']}/stages/bundling").json()
    specifics = client.get(f"{BASE}/{dashboard_plant['id']}/stages/bundling/specifics").json()

    assert stage_view["context_row"]["parameters_chip"]["applicable"] is False
    assert specifics["parameters"] == []
    assert "worker_log" in specifics["extras"]


def test_specifics_exposes_the_three_panels(client, dashboard_plant):
    body = client.get(f"{BASE}/{dashboard_plant['id']}/stages/board_manufacturing/specifics").json()

    assert set(body) >= {"hour_rows", "causes", "parameters", "extras"}
    assert set(body["causes"]) == {"downtime_pareto", "defect_pareto", "events"}


def test_acknowledging_an_alert_records_who_owned_it(client, dashboard_plant):
    response = client.post(
        f"{BASE}/{dashboard_plant['id']}/alerts/acknowledge",
        json={"alert_key": "drift:1:roll_temperature", "acknowledged_by": "supervisor"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["acknowledged_by"] == "supervisor"


def test_reason_picker_keeps_planned_and_unplanned_apart(
    client, dashboard_plant, downtime_reason_code
):
    groups = client.get(f"{BASE}/{dashboard_plant['id']}/reason-picker").json()["groups"]
    by_category = {group["category"]: group for group in groups}

    assert by_category["breakdown"]["planned"] is False


# --- Derived metrics against real rows -------------------------------------


@pytest.fixture()
def shift_with_runs(client, plant, machine_corrugator, order):
    """One 480-minute shift where the corrugator ran 360 minutes - the spec's own
    worked example, which should produce 75% utilisation once the shift is over."""
    shift = client.post(
        "/api/v1/shifts",
        json={
            "plant_id": plant["id"],
            "shift_date": "2026-09-22",
            "shift_number": 1,
            "start_time": "2026-09-22T06:00:00",
            "end_time": "2026-09-22T14:00:00",
            "scheduled_minutes": 480,
        },
    ).json()

    run = client.post(
        "/api/v1/machine-runs",
        json={
            "machine_id": machine_corrugator["id"],
            "shift_id": shift["id"],
            "order_id": order["id"],
            "start_time": "2026-09-22T06:00:00",
            "end_time": "2026-09-22T14:00:00",
            "lineal_metres": 64800,  # 360 min at 180 m/min
        },
    ).json()

    client.post(
        "/api/v1/time-logs",
        json={
            "machine_run_id": run["id"],
            "category": "running",
            "start_time": "2026-09-22T06:00:00",
            "end_time": "2026-09-22T12:00:00",
            "duration_minutes": 360,
        },
    )
    client.post(
        "/api/v1/time-logs",
        json={
            "machine_run_id": run["id"],
            "category": "breakdown",
            "start_time": "2026-09-22T12:00:00",
            "end_time": "2026-09-22T14:00:00",
            "duration_minutes": 120,
        },
    )
    client.post(
        "/api/v1/quality-records",
        json={"machine_run_id": run["id"], "good_qty": 96, "reject_qty": 4, "unit": "sheets"},
    )
    return {"shift": shift, "run": run}


def test_productivity_is_utilisation_times_rate_times_quality(client, plant, shift_with_runs):
    """The spec's worked example: 360 of 480 minutes is 75% utilisation, 180
    against a 240 m/min standard is 75% rate, 96 of 100 good is 96% quality."""
    response = client.get(
        f"{BASE}/{plant['id']}/overview",
        params={
            "range": "custom",
            "date_from": "2026-09-22",
            "date_to": "2026-09-22",
            # Pinned well after the shift closed, so nothing is pro-rated.
            "as_of": "2026-09-23T12:00:00",
        },
    )
    assert response.status_code == 200, response.text
    totals = response.json()["totals"]

    assert totals["utilisation_pct"] == pytest.approx(75.0)
    assert totals["rate_efficiency_pct"] == pytest.approx(75.0)
    assert totals["quality_pct"] == pytest.approx(96.0)
    assert totals["plant_productivity_pct"] == pytest.approx(54.0, abs=0.01)


def test_in_progress_shift_measures_against_elapsed_minutes(client, plant, shift_with_runs):
    """Utilisation an hour into a shift must not divide by the whole roster, or
    every morning reads red for no reason.

    Pinned two hours in, with 120 of those minutes logged as running, the honest
    answer is 100% - not 120/480.
    """
    response = client.get(
        f"{BASE}/{plant['id']}/overview",
        params={
            "range": "custom",
            "date_from": "2026-09-22",
            "date_to": "2026-09-22",
            "as_of": "2026-09-22T08:00:00",
        },
    )
    totals = response.json()["totals"]

    assert totals["scheduled_minutes"] == pytest.approx(120.0)
    assert totals["utilisation_pct"] == pytest.approx(100.0)


def test_loss_waterfall_adds_back_up_to_a_hundred(client, plant, shift_with_runs):
    """Potential minus not-running minus ran-slow minus rejected is exactly what
    was delivered - otherwise the picture is telling a different story from the
    productivity card above it."""
    body = client.get(
        f"{BASE}/{plant['id']}/overview",
        params={
            "range": "custom",
            "date_from": "2026-09-22",
            "date_to": "2026-09-22",
            "as_of": "2026-09-23T12:00:00",
        },
    ).json()
    steps = {step["key"]: step["value"] for step in body["waterfall"]}

    assert steps["potential"] == 100.0
    residue = (
        steps["potential"] + steps["not_running"] + steps["ran_slow"] + steps["rejected"]
    )
    assert residue == pytest.approx(steps["delivered"], abs=0.02)


def test_printing_is_measured_against_its_own_sheets_per_hour_standard(
    client, plant, machine_printer
):
    """One job carries two standards: m/min for the corrugator and sheets/hr for
    the printer. Dividing sheets per hour by a metres-per-minute figure produced
    efficiencies in the thousands."""
    order = client.post(
        "/api/v1/orders",
        json={
            "plant_id": plant["id"],
            "order_number": "ORD-PRINT",
            "standard_speed": 175,
            "standard_speed_unit": "m/min",
            "printing_standard_sheets_per_hr": 4000,
        },
    ).json()
    shift = client.post(
        "/api/v1/shifts",
        json={
            "plant_id": plant["id"],
            "shift_date": "2026-09-22",
            "shift_number": 2,
            "start_time": "2026-09-22T14:00:00",
            "end_time": "2026-09-22T22:00:00",
            "scheduled_minutes": 480,
        },
    ).json()
    run = client.post(
        "/api/v1/machine-runs",
        json={
            "machine_id": machine_printer["id"],
            "shift_id": shift["id"],
            "order_id": order["id"],
            "start_time": "2026-09-22T14:00:00",
        },
    ).json()
    client.post(
        "/api/v1/time-logs",
        json={
            "machine_run_id": run["id"],
            "category": "running",
            "start_time": "2026-09-22T14:00:00",
            "end_time": "2026-09-22T20:00:00",
            "duration_minutes": 360,
        },
    )
    # 12,000 sheets in 6 hours is 2,000/hr against a 4,000/hr standard: 50%.
    client.post(
        "/api/v1/quality-records",
        json={"machine_run_id": run["id"], "good_qty": 12000, "reject_qty": 0, "unit": "sheets"},
    )

    body = client.get(
        f"{BASE}/{plant['id']}/stages/printing",
        params={
            "range": "custom",
            "date_from": "2026-09-22",
            "date_to": "2026-09-22",
            "as_of": "2026-09-23T12:00:00",
        },
    ).json()
    run_rate = next(kpi for kpi in body["kpis"] if kpi["key"] == "run_rate_efficiency_pct")

    assert run_rate["value"] == pytest.approx(50.0, abs=0.5)


def test_planned_time_is_never_flagged_as_unplanned(client, plant, machine_corrugator):
    """Painting a changeover the same colour as a breakdown is how dashboards
    lose the shop floor, so every Pareto bar carries the planned flag."""
    setup_code = client.post(
        "/api/v1/downtime-reason-codes",
        json={"category": "setup", "code": "CHG-TEST", "description": "Order changeover"},
    ).json()
    shift = client.post(
        "/api/v1/shifts",
        json={
            "plant_id": plant["id"],
            "shift_date": "2026-09-22",
            "shift_number": 3,
            "start_time": "2026-09-22T22:00:00",
            "end_time": "2026-09-23T06:00:00",
            "scheduled_minutes": 480,
        },
    ).json()
    run = client.post(
        "/api/v1/machine-runs",
        json={
            "machine_id": machine_corrugator["id"],
            "shift_id": shift["id"],
            "start_time": "2026-09-22T22:00:00",
        },
    ).json()
    client.post(
        "/api/v1/time-logs",
        json={
            "machine_run_id": run["id"],
            "category": "setup",
            "reason_code_id": setup_code["id"],
            "start_time": "2026-09-22T22:00:00",
            "end_time": "2026-09-22T22:30:00",
            "duration_minutes": 30,
        },
    )

    body = client.get(
        f"{BASE}/{plant['id']}/stages/board_manufacturing",
        params={"range": "custom", "date_from": "2026-09-22", "date_to": "2026-09-22"},
    ).json()
    bars = body["charts"]["secondary"]["data"]

    assert bars and all(bar["planned"] for bar in bars if bar["code"] == "CHG-TEST")
