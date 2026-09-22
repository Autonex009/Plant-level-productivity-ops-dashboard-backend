import pytest


def _post(client, path, payload):
    r = client.post(path, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_worked_example_productivity(client, plant, machine_corrugator, machine_bundler, shift, order):
    """Reproduces the spec's own worked example: 360/480 running minutes (75%
    utilization), 180 m/min actual vs 240 m/min standard (75% rate efficiency),
    96% quality -> 54% plant productivity."""

    run = _post(
        client,
        "/api/v1/machine-runs",
        {
            "machine_id": machine_corrugator["id"],
            "shift_id": shift["id"],
            "order_id": order["id"],
            "start_time": "2026-09-22T06:00:00",
            "lineal_metres": 64800,  # 180 m/min x 360 running minutes
        },
    )
    _post(
        client,
        "/api/v1/time-logs",
        {
            "machine_run_id": run["id"],
            "category": "running",
            "start_time": "2026-09-22T06:00:00",
            "end_time": "2026-09-22T12:00:00",
            "duration_minutes": 360,
        },
    )
    _post(
        client,
        "/api/v1/time-logs",
        {
            "machine_run_id": run["id"],
            "category": "breakdown",
            "start_time": "2026-09-22T12:00:00",
            "end_time": "2026-09-22T14:00:00",
            "duration_minutes": 120,
        },
    )
    _post(
        client,
        "/api/v1/quality-records",
        {"machine_run_id": run["id"], "good_qty": 96, "reject_qty": 4, "unit": "pct-sample"},
    )
    _post(
        client,
        "/api/v1/material-flows",
        {"machine_run_id": run["id"], "material_type": "kraft_paper", "input_qty": 1000, "output_qty": 870, "unit": "kg"},
    )

    bundle_run = _post(
        client,
        "/api/v1/machine-runs",
        {
            "machine_id": machine_bundler["id"],
            "shift_id": shift["id"],
            "order_id": order["id"],
            "start_time": "2026-09-22T06:00:00",
        },
    )
    _post(
        client,
        "/api/v1/bundling-records",
        {"machine_run_id": bundle_run["id"], "worker_count": 4, "bundles_count": 120, "output_kg": 850},
    )

    _post(client, "/api/v1/power-readings", {"plant_id": plant["id"], "source": "grid", "kwh": 400, "recorded_at": "2026-09-22T12:00:00"})
    _post(client, "/api/v1/power-readings", {"plant_id": plant["id"], "source": "dg", "kwh": 100, "recorded_at": "2026-09-22T12:00:00"})

    r = client.get(f"/api/v1/machine-runs/{run['id']}/metrics")
    assert r.status_code == 200
    metrics = r.json()
    assert metrics["yield_pct"] == 87.0
    assert metrics["quality_pct"] == 96.0
    assert metrics["rate_efficiency_pct"] == 75.0
    assert metrics["running_minutes"] == 360.0

    r = client.get(f"/api/v1/shifts/{shift['id']}/uptime")
    assert r.status_code == 200
    uptime = r.json()
    assert len(uptime) == 1
    assert uptime[0]["uptime_pct"] == 75.0

    r = client.post(f"/api/v1/daily-plant-rollups/compute?plant_id={plant['id']}&rollup_date=2026-09-22&paper_rate_per_kg=45")
    assert r.status_code == 200, r.text
    rollup = r.json()
    assert rollup["utilization_pct"] == 75.0
    assert rollup["rate_efficiency_pct"] == 75.0
    assert rollup["quality_pct"] == 96.0
    assert rollup["plant_productivity_pct"] == 54.0
    assert rollup["overall_yield_pct"] == 85.0
    assert rollup["waste_cost_inr"] == 6750.0
    assert rollup["power_per_tonne_kwh"] == pytest.approx(574.71, rel=1e-3)
    assert rollup["grid_power_share_pct"] == 80.0


def test_defect_pareto(client, quality_record, defect_reason_code):
    _post(
        client,
        "/api/v1/defect-observations",
        {"quality_record_id": quality_record["id"], "reason_code_id": defect_reason_code["id"], "quantity": 4},
    )

    r = client.get(f"/api/v1/defect-pareto?stage={defect_reason_code['stage']}")
    assert r.status_code == 200
    data = r.json()
    assert any(d["code"] == defect_reason_code["code"] and d["quantity"] == 4.0 for d in data)

    r = client.get("/api/v1/defect-pareto?stage=printing")
    assert r.status_code == 200
    assert r.json() == []


def test_machine_run_metrics_missing_data_returns_nulls(client, machine_run):
    r = client.get(f"/api/v1/machine-runs/{machine_run['id']}/metrics")
    assert r.status_code == 200
    metrics = r.json()
    assert metrics["yield_pct"] is None
    assert metrics["quality_pct"] is None
    assert metrics["bundles_per_hour"] is None
    assert metrics["running_minutes"] == 0.0
