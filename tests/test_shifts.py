from tests.helpers import assert_crud_lifecycle


def test_shift_crud(client, plant):
    assert_crud_lifecycle(
        client,
        "/api/v1/shifts",
        create_payload={
            "plant_id": plant["id"],
            "shift_date": "2026-09-22",
            "shift_number": 1,
            "start_time": "2026-09-22T06:00:00",
            "end_time": "2026-09-22T14:00:00",
            "scheduled_minutes": 480,
        },
        patch_payload={"scheduled_minutes": 460},
    )


def test_shift_date_range_filter(client, plant):
    client.post(
        "/api/v1/shifts",
        json={
            "plant_id": plant["id"],
            "shift_date": "2026-09-20",
            "shift_number": 1,
            "start_time": "2026-09-20T06:00:00",
            "end_time": "2026-09-20T14:00:00",
            "scheduled_minutes": 480,
        },
    )
    client.post(
        "/api/v1/shifts",
        json={
            "plant_id": plant["id"],
            "shift_date": "2026-09-25",
            "shift_number": 1,
            "start_time": "2026-09-25T06:00:00",
            "end_time": "2026-09-25T14:00:00",
            "scheduled_minutes": 480,
        },
    )

    r = client.get(f"/api/v1/shifts?plant_id={plant['id']}&date_from=2026-09-21&date_to=2026-09-26")
    assert r.status_code == 200
    dates = [s["shift_date"] for s in r.json()]
    assert dates == ["2026-09-25"]
