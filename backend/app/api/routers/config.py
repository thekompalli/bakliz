from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_db, require_user
from app.db.models import Config

router = APIRouter()


class ConfigOut(BaseModel):
    industry: str
    location: str
    company_size_min: int
    daily_objective: int
    email_subject_template: str
    email_body_template: str
    alert_email: str
    run_mode: str


class ConfigUpdate(BaseModel):
    industry: str | None = None
    location: str | None = None
    company_size_min: int | None = Field(default=None, ge=1)
    daily_objective: int | None = Field(default=None, ge=0)
    email_subject_template: str | None = None
    email_body_template: str | None = None
    alert_email: str | None = None
    run_mode: str | None = Field(default=None, pattern="^(live|dry_run)$")


def _get_or_create(db: Session) -> Config:
    cfg = db.execute(select(Config).where(Config.id == 1)).scalar_one_or_none()
    if cfg is None:
        cfg = Config(id=1)
        db.add(cfg)
        db.commit()
    return cfg


@router.get("/config", response_model=ConfigOut)
def get_config(_: dict = Depends(require_user), db: Session = Depends(require_db)) -> ConfigOut:
    cfg = _get_or_create(db)
    return ConfigOut(
        industry=cfg.industry,
        location=cfg.location,
        company_size_min=cfg.company_size_min,
        daily_objective=cfg.daily_objective,
        email_subject_template=cfg.email_subject_template,
        email_body_template=cfg.email_body_template,
        alert_email=cfg.alert_email,
        run_mode=cfg.run_mode,
    )


@router.put("/config", response_model=ConfigOut)
def update_config(payload: ConfigUpdate, _: dict = Depends(require_user), db: Session = Depends(require_db)) -> ConfigOut:
    cfg = _get_or_create(db)

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(cfg, k, v)
    cfg.updated_at = datetime.now(timezone.utc)

    db.add(cfg)
    db.commit()
    db.refresh(cfg)

    return ConfigOut(
        industry=cfg.industry,
        location=cfg.location,
        company_size_min=cfg.company_size_min,
        daily_objective=cfg.daily_objective,
        email_subject_template=cfg.email_subject_template,
        email_body_template=cfg.email_body_template,
        alert_email=cfg.alert_email,
        run_mode=cfg.run_mode,
    )
