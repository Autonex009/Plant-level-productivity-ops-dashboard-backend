from tests.helpers import assert_crud_lifecycle


def test_order_crud(client, plant):
    assert_crud_lifecycle(
        client,
        "/api/v1/orders",
        create_payload={"plant_id": plant["id"], "order_number": "ORD-100", "ply_construction": "3-ply", "flute_profile": "B"},
        patch_payload={"ply_construction": "5-ply"},
    )


def test_order_number_filter(client, plant):
    client.post("/api/v1/orders", json={"plant_id": plant["id"], "order_number": "ORD-XYZ"})
    r = client.get("/api/v1/orders?order_number=ORD-XYZ")
    assert r.status_code == 200
    assert len(r.json()) == 1
