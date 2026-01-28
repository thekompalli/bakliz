from app.db.models import Base, Config, ProviderLog
from app.db.session import SessionLocal, init_engine
from app.services.run_engine import run_daily


def test_provider_logs_written_in_demo_mode(monkeypatch):
    monkeypatch.setenv("BAKLIZ_DEMO_MODE", "true")
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)

    engine = init_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    db = SessionLocal()
    db.add(
        Config(
            id=1,
            industry="Logistics",
            location="France",
            company_size_min=50,
            daily_objective=2,
            email_subject_template="Hello {{Company}}",
            email_body_template="Hi {{FirstName}} at {{Company}}",
            alert_email="alerts@example.com",
            run_mode="dry_run",
        )
    )
    db.commit()

    try:
        summary = run_daily(db=db, dry_run=True, overrides={"daily_objective": 2})
        assert summary.run_id

        rows = db.query(ProviderLog).filter(ProviderLog.provider == "linkup").all()
        kinds = {r.kind for r in rows}
        assert "company_search" in kinds
        assert "contacts" in kinds
    finally:
        db.close()

