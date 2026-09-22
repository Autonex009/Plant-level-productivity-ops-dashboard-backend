from tests.helpers import assert_crud_lifecycle


def test_parameter_reading_crud(client, machine_corrugator, metric_definition, machine_run):
    assert_crud_lifecycle(
        client,
        "/api/v1/parameter-readings",
        create_payload={
            "machine_id": machine_corrugator["id"],
            "machine_run_id": machine_run["id"],
            "metric_definition_id": metric_definition["id"],
            "source": "plc_live",
            "value": 145.5,
            "recorded_at": "2026-09-22T08:00:00",
        },
        patch_payload={"value": 150.0},
    )


def test_parameter_reading_filters(client, machine_corrugator, metric_definition):
    client.post(
        "/api/v1/parameter-readings",
        json={
            "machine_id": machine_corrugator["id"],
            "metric_definition_id": metric_definition["id"],
            "source": "qa_sample",
            "value": 100,
            "recorded_at": "2026-09-22T09:00:00",
        },
    )
    r = client.get(f"/api/v1/parameter-readings?machine_id={machine_corrugator['id']}&source=qa_sample")
    assert r.status_code == 200
    assert len(r.json()) == 1
