from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_db, require_user
from app.db.models import ProviderLog

router = APIRouter()


class ProviderLogItem(BaseModel):
    id: int
    created_at: str
    run_id: str | None
    provider: str
    kind: str
    key: str | None
    request: dict
    response: dict


class ProviderLogListResponse(BaseModel):
    items: list[ProviderLogItem]
    total: int
    page: int
    page_size: int


@router.get("/provider-logs", response_model=ProviderLogListResponse)
def list_provider_logs(
    _: dict = Depends(require_user),
    db: Session = Depends(require_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    provider: str | None = Query(None),
    kind: str | None = Query(None),
    run_id: str | None = Query(None),
    key: str | None = Query(None),
) -> ProviderLogListResponse:
    q = select(ProviderLog)

    if provider:
        q = q.where(ProviderLog.provider == provider)
    if kind:
        q = q.where(ProviderLog.kind == kind)
    if run_id:
        q = q.where(ProviderLog.run_id == uuid.UUID(run_id))
    if key:
        q = q.where(ProviderLog.key == key)

    total = int(db.execute(select(func.count()).select_from(q.subquery())).scalar_one())
    rows = (
        db.execute(
            q.order_by(ProviderLog.created_at.desc(), ProviderLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    items = [
        ProviderLogItem(
            id=r.id,
            created_at=r.created_at.isoformat(),
            run_id=str(r.run_id) if r.run_id else None,
            provider=r.provider,
            kind=r.kind,
            key=r.key,
            request=r.request or {},
            response=r.response or {},
        )
        for r in rows
    ]
    return ProviderLogListResponse(items=items, total=total, page=page, page_size=page_size)

