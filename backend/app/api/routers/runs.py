from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_db, require_user
from app.db.models import RunLog

router = APIRouter()


class RunRow(BaseModel):
    run_id: str
    started_at: str
    finished_at: str | None
    quota: int
    created_drafts: int
    excluded_count: int
    enrich_failed_count: int
    pool_exhausted: bool
    run_mode: str


class RunsListResponse(BaseModel):
    items: list[RunRow]
    page: int
    page_size: int
    total: int


@router.get("/runs", response_model=RunsListResponse)
def list_runs(
    _: dict = Depends(require_user),
    db: Session = Depends(require_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> RunsListResponse:
    total = db.execute(select(func.count()).select_from(RunLog)).scalar_one()
    rows = (
        db.execute(select(RunLog).order_by(RunLog.started_at.desc()).offset((page - 1) * page_size).limit(page_size))
        .scalars()
        .all()
    )
    items = [
        RunRow(
            run_id=str(r.run_id),
            started_at=r.started_at.isoformat(),
            finished_at=r.finished_at.isoformat() if r.finished_at else None,
            quota=r.quota,
            created_drafts=r.created_drafts,
            excluded_count=r.excluded_count,
            enrich_failed_count=r.enrich_failed_count,
            pool_exhausted=r.pool_exhausted,
            run_mode=r.run_mode,
        )
        for r in rows
    ]
    return RunsListResponse(items=items, page=page, page_size=page_size, total=total)

