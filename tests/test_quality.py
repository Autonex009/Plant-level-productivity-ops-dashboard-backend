from tests.helpers import assert_crud_lifecycle


def test_quality_record_crud(client, machine_run):
    assert_crud_lifecycle(
        client,
        "/api/v1/quality-records",
        create_payload={"machine_run_id": machine_run["id"], "good_qty": 96, "reject_qty": 4, "unit": "sheets"},
        patch_payload={"reject_qty": 5},
    )


def test_defect_observation_crud(client, quality_record, defect_reason_code):
    assert_crud_lifecycle(
        client,
        "/api/v1/defect-observations",
        create_payload={
            "quality_record_id": quality_record["id"],
            "reason_code_id": defect_reason_code["id"],
            "quantity": 4,
            "notes": "test note",
        },
        patch_payload={"quantity": 5},
    )


def test_defect_observation_filter(client, quality_record, defect_reason_code):
    client.post(
        "/api/v1/defect-observations",
        json={"quality_record_id": quality_record["id"], "reason_code_id": defect_reason_code["id"], "quantity": 2},
    )
    r = client.get(f"/api/v1/defect-observations?quality_record_id={quality_record['id']}")
    assert r.status_code == 200
    assert len(r.json()) == 1
