from tests.helpers import assert_crud_lifecycle


def test_metric_definition_crud(client):
    assert_crud_lifecycle(
        client,
        "/api/v1/metric-definitions",
        create_payload={
            "code": "test_yield",
            "name": "Test Yield",
            "definition": "x/y",
            "unit": "%",
            "category": "material",
            "stage": "board_manufacturing",
        },
        patch_payload={"name": "Test Yield Renamed"},
    )


def test_metric_definition_filters(client):
    client.post(
        "/api/v1/metric-definitions",
        json={"code": "plant_kpi", "name": "Plant KPI", "definition": "d", "unit": "%", "category": "throughput"},
    )
    r = client.get("/api/v1/metric-definitions?category=throughput")
    assert r.status_code == 200
    assert any(m["code"] == "plant_kpi" for m in r.json())


def test_plant_metric_target_crud(client, plant, metric_definition):
    assert_crud_lifecycle(
        client,
        "/api/v1/plant-metric-targets",
        create_payload={
            "plant_id": plant["id"],
            "metric_definition_id": metric_definition["id"],
            "target_value": 90.0,
            "effective_from": "2026-01-01",
        },
        patch_payload={"target_value": 95.0},
    )
