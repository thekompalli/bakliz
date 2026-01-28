from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_db, require_user
from app.db.models import BlacklistEntry
from app.services.normalization import normalize_company_name, normalize_domain

router = APIRouter()


class BlacklistEntryOut(BaseModel):
    id: int
    entry_type: str
    value_raw: str
    value_norm: str
    created_at: str


class BlacklistListResponse(BaseModel):
    items: list[BlacklistEntryOut]
    page: int
    page_size: int
    total: int


class BlacklistCreate(BaseModel):
    entry_type: str = Field(pattern="^(company_name|domain)$")
    value: str = Field(min_length=1)


@router.get("/blacklist", response_model=BlacklistListResponse)
def list_blacklist(
    _: dict = Depends(require_user),
    db: Session = Depends(require_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> BlacklistListResponse:
    total = db.execute(select(func.count()).select_from(BlacklistEntry)).scalar_one()
    rows = (
        db.execute(
            select(BlacklistEntry)
            .order_by(BlacklistEntry.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    items = [
        BlacklistEntryOut(
            id=r.id,
            entry_type=r.entry_type,
            value_raw=r.value_raw,
            value_norm=r.value_norm,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
    return BlacklistListResponse(items=items, page=page, page_size=page_size, total=total)


@router.post("/blacklist", response_model=BlacklistEntryOut, status_code=status.HTTP_201_CREATED)
def create_blacklist(payload: BlacklistCreate, _: dict = Depends(require_user), db: Session = Depends(require_db)) -> BlacklistEntryOut:
    value_raw = payload.value.strip()
    if payload.entry_type == "domain":
        value_norm = normalize_domain(value_raw)
    else:
        value_norm = normalize_company_name(value_raw)

    if not value_norm:
        raise HTTPException(status_code=400, detail="Invalid value")

    row = BlacklistEntry(entry_type=payload.entry_type, value_raw=value_raw, value_norm=value_norm)
    db.add(row)
    db.commit()
    db.refresh(row)

    return BlacklistEntryOut(
        id=row.id,
        entry_type=row.entry_type,
        value_raw=row.value_raw,
        value_norm=row.value_norm,
        created_at=row.created_at.isoformat(),
    )


@router.delete("/blacklist/{entry_id}", status_code=status.HTTP_200_OK)
def delete_blacklist(entry_id: int, _: dict = Depends(require_user), db: Session = Depends(require_db)) -> dict:
    row = db.execute(select(BlacklistEntry).where(BlacklistEntry.id == entry_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"deleted": True}

