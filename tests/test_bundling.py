from tests.helpers import assert_crud_lifecycle


def test_bundling_record_crud(client, machine_bundler, shift, order):
    r = client.post(
        "/api/v1/machine-runs",
        json={
            "machine_id": machine_bundler["id"],
            "shift_id": shift["id"],
            "order_id": order["id"],
            "start_time": "2026-09-22T06:00:00",
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()

    assert_crud_lifecycle(
        client,
        "/api/v1/bundling-records",
        create_payload={
            "machine_run_id": run["id"],
            "worker_count": 4,
            "bundles_count": 100,
            "output_kg": 850,
            "starvation_minutes": 10,
        },
        patch_payload={"bundles_count": 110},
    )
