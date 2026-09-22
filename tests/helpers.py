def assert_crud_lifecycle(client, prefix: str, create_payload: dict, patch_payload: dict) -> int:
    """Drives one entity through create -> get -> list -> patch -> delete -> 404,
    mirroring the generic CRUD router every entity is built on."""

    r = client.post(prefix, json=create_payload)
    assert r.status_code == 201, r.text
    obj = r.json()
    obj_id = obj["id"]
    for key, value in create_payload.items():
        if key in obj:
            assert obj[key] == value, f"create: {key} expected {value!r}, got {obj[key]!r}"

    r = client.get(f"{prefix}/{obj_id}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == obj_id

    r = client.get(prefix)
    assert r.status_code == 200, r.text
    assert any(item["id"] == obj_id for item in r.json())

    r = client.patch(f"{prefix}/{obj_id}", json=patch_payload)
    assert r.status_code == 200, r.text
    updated = r.json()
    for key, value in patch_payload.items():
        assert updated[key] == value, f"patch: {key} expected {value!r}, got {updated[key]!r}"

    r = client.delete(f"{prefix}/{obj_id}")
    assert r.status_code == 204, r.text

    r = client.get(f"{prefix}/{obj_id}")
    assert r.status_code == 404

    return obj_id
