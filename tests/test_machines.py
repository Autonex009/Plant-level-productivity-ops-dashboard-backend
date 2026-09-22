from tests.helpers import assert_crud_lifecycle


def test_machine_crud(client, plant):
    assert_crud_lifecycle(
        client,
        "/api/v1/machines",
        create_payload={"plant_id": plant["id"], "stage": "board_manufacturing", "machine_code": "M-1", "name": "Machine 1"},
        patch_payload={"name": "Machine 1 renamed"},
    )


def test_machine_filter_by_plant_and_stage(client, plant):
    client.post(
        "/api/v1/machines",
        json={"plant_id": plant["id"], "stage": "printing", "machine_code": "P-1", "name": "Printer"},
    )
    client.post(
        "/api/v1/machines",
        json={"plant_id": plant["id"], "stage": "bundling", "machine_code": "B-1", "name": "Bundler"},
    )

    r = client.get(f"/api/v1/machines?plant_id={plant['id']}&stage=printing")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["machine_code"] == "P-1"
