from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_db, require_user
from app.services.run_engine import RunSummary, run_daily, run_daily_iter

router = APIRouter()


class RunRequest(BaseModel):
    overrides: dict | None = None


class RunResponse(BaseModel):
    run_id: str
    created_drafts: int
    quota: int
    excluded_count: int
    enrich_failed_count: int
    pool_exhausted: bool
    errors: list[dict]


@router.post("/run", response_model=RunResponse)
def run(
    payload: RunRequest,
    _: dict = Depends(require_user),
    db: Session = Depends(require_db),
    dry_run: bool = Query(False),
) -> RunResponse:
    summary: RunSummary = run_daily(db=db, dry_run=dry_run, overrides=payload.overrides)
    return RunResponse(
        run_id=str(summary.run_id),
        created_drafts=summary.created_drafts,
        quota=summary.quota,
        excluded_count=summary.excluded_count,
        enrich_failed_count=summary.enrich_failed_count,
        pool_exhausted=summary.pool_exhausted,
        errors=summary.errors,
    )


@router.post("/run/stream")
def run_stream(
    payload: RunRequest,
    _: dict = Depends(require_user),
    db: Session = Depends(require_db),
    dry_run: bool = Query(False),
):
    def gen():
        for ev in run_daily_iter(db=db, dry_run=dry_run, overrides=payload.overrides):
            yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(gen(), media_type="application/x-ndjson")
