from tests.helpers import assert_crud_lifecycle


def test_power_reading_crud(client, plant):
    assert_crud_lifecycle(
        client,
        "/api/v1/power-readings",
        create_payload={"plant_id": plant["id"], "source": "grid", "kwh": 400, "recorded_at": "2026-09-22T12:00:00"},
        patch_payload={"kwh": 420},
    )


def test_power_reading_filter_by_source(client, plant):
    client.post(
        "/api/v1/power-readings",
        json={"plant_id": plant["id"], "source": "dg", "kwh": 100, "recorded_at": "2026-09-22T12:00:00"},
    )
    r = client.get(f"/api/v1/power-readings?plant_id={plant['id']}&source=dg")
    assert r.status_code == 200
    assert len(r.json()) == 1
