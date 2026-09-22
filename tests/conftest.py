import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.main import app
from app.models import Base

# Defaults to the docker-compose database; override with TEST_DATABASE_URL.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://plantops:plantops@localhost:5432/plant_ops_dashboard_test",
)

engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _truncate_all() -> None:
    table_names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        _truncate_all()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- Shared fixtures for FK-dependent entities -----------------------------


@pytest.fixture()
def plant(client):
    r = client.post("/api/v1/plants", json={"name": "Test Plant", "location": "Pune", "line_type": "semi_automatic"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def machine_corrugator(client, plant):
    r = client.post(
        "/api/v1/machines",
        json={"plant_id": plant["id"], "stage": "board_manufacturing", "machine_code": "CORR-1", "name": "Corrugator 1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def machine_printer(client, plant):
    r = client.post(
        "/api/v1/machines",
        json={"plant_id": plant["id"], "stage": "printing", "machine_code": "PRINT-1", "name": "Printer 1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def machine_bundler(client, plant):
    r = client.post(
        "/api/v1/machines",
        json={"plant_id": plant["id"], "stage": "bundling", "machine_code": "BUNDLE-1", "name": "Bundler 1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def shift(client, plant):
    r = client.post(
        "/api/v1/shifts",
        json={
            "plant_id": plant["id"],
            "shift_date": "2026-09-22",
            "shift_number": 1,
            "start_time": "2026-09-22T06:00:00",
            "end_time": "2026-09-22T14:00:00",
            "scheduled_minutes": 480,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def order(client, plant):
    r = client.post(
        "/api/v1/orders",
        json={"plant_id": plant["id"], "order_number": "ORD-1", "standard_speed": 240, "standard_speed_unit": "m/min"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def machine_run(client, machine_corrugator, shift, order):
    r = client.post(
        "/api/v1/machine-runs",
        json={
            "machine_id": machine_corrugator["id"],
            "shift_id": shift["id"],
            "order_id": order["id"],
            "start_time": "2026-09-22T06:00:00",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def metric_definition(client):
    r = client.post(
        "/api/v1/metric-definitions",
        json={
            "code": "test_metric",
            "name": "Test metric",
            "definition": "For testing",
            "unit": "%",
            "category": "quality",
            "stage": "board_manufacturing",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def downtime_reason_code(client):
    r = client.post(
        "/api/v1/downtime-reason-codes",
        json={"category": "breakdown", "code": "TEST-DT", "description": "Test downtime"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def defect_reason_code(client):
    r = client.post(
        "/api/v1/defect-reason-codes",
        json={"stage": "board_manufacturing", "code": "TEST-DEF", "description": "Test defect"},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def quality_record(client, machine_run):
    r = client.post(
        "/api/v1/quality-records",
        json={"machine_run_id": machine_run["id"], "good_qty": 96, "reject_qty": 4, "unit": "sheets"},
    )
    assert r.status_code == 201, r.text
    return r.json()
