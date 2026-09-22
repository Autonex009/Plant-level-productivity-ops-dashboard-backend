from tests.helpers import assert_crud_lifecycle


def test_plant_crud(client):
    assert_crud_lifecycle(
        client,
        "/api/v1/plants",
        create_payload={"name": "Pune Corrugators", "location": "Pune", "line_type": "semi_automatic"},
        patch_payload={"location": "Mumbai"},
    )


def test_plant_validation_error(client):
    r = client.post("/api/v1/plants", json={"name": "Bad", "line_type": "not_a_real_type"})
    assert r.status_code == 422


def test_plant_not_found(client):
    r = client.get("/api/v1/plants/999999")
    assert r.status_code == 404
