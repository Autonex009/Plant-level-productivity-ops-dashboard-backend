from tests.helpers import assert_crud_lifecycle


def test_downtime_reason_code_crud(client):
    assert_crud_lifecycle(
        client,
        "/api/v1/downtime-reason-codes",
        create_payload={"category": "setup", "code": "PLATE-CHANGE", "description": "Plate change"},
        patch_payload={"description": "Plate change (updated)"},
    )


def test_downtime_reason_code_filter(client):
    client.post(
        "/api/v1/downtime-reason-codes",
        json={"category": "waiting", "code": "WAIT-REELS", "description": "Waiting for reels"},
    )
    r = client.get("/api/v1/downtime-reason-codes?category=waiting")
    assert r.status_code == 200
    assert any(c["code"] == "WAIT-REELS" for c in r.json())


def test_defect_reason_code_crud(client):
    assert_crud_lifecycle(
        client,
        "/api/v1/defect-reason-codes",
        create_payload={"stage": "printing", "code": "SMUDGE", "description": "Print smudge"},
        patch_payload={"description": "Print smudge (updated)"},
    )


def test_defect_reason_code_filter(client):
    client.post(
        "/api/v1/defect-reason-codes",
        json={"stage": "bundling", "code": "MISCOUNT", "description": "Bundle miscount"},
    )
    r = client.get("/api/v1/defect-reason-codes?stage=bundling")
    assert r.status_code == 200
    assert any(c["code"] == "MISCOUNT" for c in r.json())
