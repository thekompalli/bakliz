from sqlalchemy.orm import Session

from app.db.models import Base, Config
from app.db.session import SessionLocal, init_engine
from app.services.run_engine import run_daily


def _setup_db() -> Session:
    engine = init_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.add(
        Config(
            id=1,
            industry="Logistics",
            location="France",
            company_size_min=50,
            daily_objective=5,
            email_subject_template="Hi {{Company}}",
            email_body_template="Hi {{FirstName}} at {{Company}}",
            alert_email="alerts@example.com",
            run_mode="dry_run",
        )
    )
    db.commit()
    return db


def test_guarantee_loop_reaches_quota_in_demo_mode(monkeypatch):
    monkeypatch.setenv("BAKLIZ_DEMO_MODE", "true")
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    db = _setup_db()
    try:
        summary = run_daily(db=db, dry_run=True, overrides={"daily_objective": 5})
        assert summary.created_drafts == summary.quota
        assert summary.pool_exhausted is False
    finally:
        db.close()


def test_guarantee_loop_pool_exhausted(monkeypatch):
    monkeypatch.setenv("BAKLIZ_DEMO_MODE", "true")
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    from app.services import linkup_service
    from app.services.linkup_service import CompanyItem

    def small_pool(_cfg):
        return [CompanyItem(company_name="TinyCo", company_domain="tiny.baklizdemo.local", employee_count=120)]

    monkeypatch.setattr(linkup_service, "_demo_companies", small_pool)

    db = _setup_db()
    try:
        summary = run_daily(db=db, dry_run=True, overrides={"daily_objective": 4})
        assert summary.created_drafts < summary.quota
        assert summary.pool_exhausted is True
    finally:
        db.close()
