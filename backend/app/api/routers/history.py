from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_db, require_user
from app.db.models import History

router = APIRouter()


class HistoryRow(BaseModel):
    date_time: str
    company_name: str | None
    company_domain: str | None
    employee_count: int | None
    first_name: str | None
    last_name: str | None
    email: str | None
    job_title: str | None
    status_code: str
    status_detail: str | None
    run_id: str


class HistoryListResponse(BaseModel):
    items: list[HistoryRow]
    page: int
    page_size: int
    total: int


@router.get("/history", response_model=HistoryListResponse)
def list_history(
    _: dict = Depends(require_user),
    db: Session = Depends(require_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    status_code: str | None = None,
    company: str | None = None,
    domain: str | None = None,
    run_id: uuid.UUID | None = None,
) -> HistoryListResponse:
    q = select(History)
    count_q = select(func.count()).select_from(History)

    def apply_filters(stmt):
        if from_date:
            stmt = stmt.where(History.date_time >= from_date)
        if to_date:
            stmt = stmt.where(History.date_time <= to_date)
        if status_code:
            stmt = stmt.where(History.status_code == status_code)
        if company:
            stmt = stmt.where(History.company_name.ilike(f"%{company}%"))
        if domain:
            stmt = stmt.where(History.company_domain.ilike(f"%{domain}%"))
        if run_id:
            stmt = stmt.where(History.run_id == run_id)
        return stmt

    q = apply_filters(q)
    count_q = apply_filters(count_q)

    total = db.execute(count_q).scalar_one()
    rows = (
        db.execute(q.order_by(History.date_time.desc()).offset((page - 1) * page_size).limit(page_size))
        .scalars()
        .all()
    )

    items = [
        HistoryRow(
            date_time=r.date_time.isoformat(),
            company_name=r.company_name,
            company_domain=r.company_domain,
            employee_count=r.employee_count,
            first_name=r.first_name,
            last_name=r.last_name,
            email=r.email,
            job_title=r.job_title,
            status_code=r.status_code,
            status_detail=r.status_detail,
            run_id=str(r.run_id),
        )
        for r in rows
    ]
    return HistoryListResponse(items=items, page=page, page_size=page_size, total=total)


class HistoryClearResponse(BaseModel):
    deleted: int


@router.delete("/history", response_model=HistoryClearResponse)
def clear_history(
    _: dict = Depends(require_user),
    db: Session = Depends(require_db),
    confirm: str = Query(..., description="Must be exactly: DELETE"),
    run_id: uuid.UUID | None = None,
) -> HistoryClearResponse:
    if confirm != "DELETE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid confirm value")

    stmt = delete(History)
    if run_id is not None:
        stmt = stmt.where(History.run_id == run_id)

    result = db.execute(stmt)
    db.commit()
    return HistoryClearResponse(deleted=int(result.rowcount or 0))
