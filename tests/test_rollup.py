from tests.helpers import assert_crud_lifecycle


def test_daily_plant_rollup_crud(client, plant):
    assert_crud_lifecycle(
        client,
        "/api/v1/daily-plant-rollups",
        create_payload={"plant_id": plant["id"], "rollup_date": "2026-09-22", "overall_yield_pct": 85.0},
        patch_payload={"overall_yield_pct": 87.0},
    )
