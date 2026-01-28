from fastapi.testclient import TestClient

from app.db.models import Base, Config, History
from app.db.session import SessionLocal, init_engine
from app.main import create_app


def test_api_run_dry_logs_history():
    import os

    os.environ["BAKLIZ_DEMO_MODE"] = "true"
    os.environ.pop("LINKUP_API_KEY", None)
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD"] = "admin"
    os.environ["JWT_SECRET"] = "test-secret"

    engine = init_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    db = SessionLocal()
    db.add(
        Config(
            id=1,
            industry="Logistics",
            location="France",
            company_size_min=50,
            daily_objective=3,
            email_subject_template="Hello {{Company}}",
            email_body_template="Hi {{FirstName}} at {{Company}}",
            alert_email="alerts@example.com",
            run_mode="dry_run",
        )
    )
    db.commit()
    db.close()

    app = create_app()
    client = TestClient(app)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    resp = client.post(
        "/api/run?dry_run=true",
        headers={"Authorization": f"Bearer {token}"},
        json={"overrides": {"daily_objective": 3}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created_drafts"] == body["quota"] or body["pool_exhausted"] is True

    db2 = SessionLocal()
    statuses = {r.status_code for r in db2.query(History).all()}
    db2.close()

    assert "DRY_RUN_READY" in statuses or "POOL_EXHAUSTED" in statuses
