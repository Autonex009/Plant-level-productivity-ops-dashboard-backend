from tests.helpers import assert_crud_lifecycle


def test_machine_run_crud(client, machine_corrugator, shift, order):
    assert_crud_lifecycle(
        client,
        "/api/v1/machine-runs",
        create_payload={
            "machine_id": machine_corrugator["id"],
            "shift_id": shift["id"],
            "order_id": order["id"],
            "start_time": "2026-09-22T06:00:00",
            "lineal_metres": 1000,
        },
        patch_payload={"lineal_metres": 2000},
    )


def test_machine_run_filters(client, machine_run):
    r = client.get(f"/api/v1/machine-runs?machine_id={machine_run['machine_id']}")
    assert r.status_code == 200
    assert any(run["id"] == machine_run["id"] for run in r.json())

    r = client.get(f"/api/v1/machine-runs?shift_id={machine_run['shift_id']}")
    assert r.status_code == 200
    assert any(run["id"] == machine_run["id"] for run in r.json())


def test_material_flow_crud(client, machine_run):
    assert_crud_lifecycle(
        client,
        "/api/v1/material-flows",
        create_payload={
            "machine_run_id": machine_run["id"],
            "material_type": "kraft_paper",
            "input_qty": 1000,
            "output_qty": 870,
            "unit": "kg",
        },
        patch_payload={"output_qty": 880},
    )


def test_time_log_crud(client, machine_run):
    assert_crud_lifecycle(
        client,
        "/api/v1/time-logs",
        create_payload={
            "machine_run_id": machine_run["id"],
            "category": "running",
            "start_time": "2026-09-22T06:00:00",
            "end_time": "2026-09-22T12:00:00",
            "duration_minutes": 360,
        },
        patch_payload={"duration_minutes": 350},
    )


def test_time_log_filter_by_category(client, machine_run):
    client.post(
        "/api/v1/time-logs",
        json={
            "machine_run_id": machine_run["id"],
            "category": "breakdown",
            "start_time": "2026-09-22T12:00:00",
            "end_time": "2026-09-22T13:00:00",
            "duration_minutes": 60,
        },
    )
    r = client.get(f"/api/v1/time-logs?machine_run_id={machine_run['id']}&category=breakdown")
    assert r.status_code == 200
    assert len(r.json()) == 1
