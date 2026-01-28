from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.settings import Settings
from app.db.models import History, ZeliqEnrichmentJob
from app.services.normalization import domain_matches, normalize_company_name, normalize_domain, normalize_person_name
from app.services.zeliq_service import ZeliqService


router = APIRouter(prefix="/integrations/zeliq")


@router.post("/callback/email")
def zeliq_email_callback(
    *,
    job_id: uuid.UUID = Query(...),
    secret: str = Query(...),
    payload: Any = Body(...),
    db: Session = Depends(get_db),
) -> dict:
    settings = Settings()
    expected = settings.zeliq_webhook_secret or ""
    if expected and secret != expected:
        raise HTTPException(status_code=401, detail="Invalid secret")

    job = db.execute(select(ZeliqEnrichmentJob).where(ZeliqEnrichmentJob.job_id == job_id)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")

    service = ZeliqService(db=db, run_id=job.run_id or uuid.uuid4())
    try:
        emails = service.handle_email_callback(job_id=job_id, payload=payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown job_id") from None

    # Write a HISTORY row so the UI shows what arrived, even if it arrived after /run finished.
    # This does NOT create drafts; it's purely an audit record.
    person_key = job.person_key
    first_name = str((job.request_payload or {}).get("first_name") or "").strip() or None
    last_name = str((job.request_payload or {}).get("last_name") or "").strip() or None
    company_domain = normalize_domain(str((job.request_payload or {}).get("company_domain") or job.company_domain_norm or ""))
    company_name = str((job.request_payload or {}).get("company_name") or "").strip() or None
    company_name_norm = normalize_company_name(company_name)
    company_domain_norm = normalize_domain(company_domain)

    best_email: str | None = None
    mismatch_domain: str | None = None
    if emails:
        # Prefer emails that match the company domain/subdomains. If none match, record mismatch explicitly.
        for e in emails:
            e2 = (e or "").strip()
            if "@" not in e2:
                continue
            dom = normalize_domain(e2.split("@", 1)[1])
            if company_domain_norm and domain_matches(dom, company_domain_norm):
                best_email = e2
                break
        if not best_email:
            best_email = (emails[0] or "").strip()
            if "@" in best_email:
                mismatch_domain = normalize_domain(best_email.split("@", 1)[1])

    if best_email:
        if mismatch_domain and company_domain_norm and not domain_matches(mismatch_domain, company_domain_norm):
            status_code = "ENRICH_FAILED"
            status_detail = f"zeliq callback email domain mismatch: {mismatch_domain} != {company_domain_norm}"
        else:
            status_code = "ENRICH_CALLBACK"
            status_detail = "zeliq callback email received"
    else:
        status_code = "ENRICH_CALLBACK"
        status_detail = "zeliq callback received (no email)"

    email_norm = best_email.strip().lower() if best_email else None
    # Normalize person names lightly for consistency.
    fn2 = normalize_person_name(first_name) or first_name
    ln2 = normalize_person_name(last_name) or last_name
    run_id_for_history = job.run_id or uuid.uuid4()

    # Avoid duplicate HISTORY rows:
    # - If /run already logged the same email+company+run, don't insert again.
    # - If /run logged "no email found" for the same person, update that row to include the callback email.
    existing_same_email = None
    if email_norm and company_domain_norm and job.run_id:
        existing_same_email = (
            db.execute(
                select(History)
                .where(History.run_id == run_id_for_history)
                .where(History.company_domain_norm == company_domain_norm)
                .where(History.email_norm == email_norm)
                .limit(1)
            )
            .scalars()
            .first()
        )
    if existing_same_email is not None:
        return {"ok": True, "job_id": str(job_id), "emails": emails, "history": "skipped_duplicate"}

    existing_same_person = None
    if company_domain_norm and job.run_id and fn2 and ln2:
        existing_same_person = (
            db.execute(
                select(History)
                .where(History.run_id == run_id_for_history)
                .where(History.company_domain_norm == company_domain_norm)
                .where(History.first_name == fn2)
                .where(History.last_name == ln2)
                .order_by(History.date_time.desc(), History.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )

    if existing_same_person is not None:
        # If the run already recorded a domain mismatch, don't record it again.
        if status_code == "ENRICH_FAILED" and (existing_same_person.status_detail or "").find("domain mismatch") >= 0:
            return {"ok": True, "job_id": str(job_id), "emails": emails, "history": "skipped_duplicate"}
        # If the run recorded "no email found", upgrade that row with callback data.
        if (existing_same_person.status_code or "") == "ENRICH_FAILED" and (
            (existing_same_person.status_detail or "").strip() == "no email found"
        ):
            existing_same_person.email = best_email
            existing_same_person.email_norm = email_norm
            existing_same_person.status_code = status_code
            existing_same_person.status_detail = status_detail
            db.add(existing_same_person)
            db.commit()
            return {"ok": True, "job_id": str(job_id), "emails": emails, "history": "updated_existing"}

    db.add(
        History(
            company_name=company_name,
            company_domain=company_domain or None,
            employee_count=None,
            first_name=fn2,
            last_name=ln2,
            email=best_email,
            job_title=None,
            status_code=status_code,
            status_detail=status_detail,
            run_id=run_id_for_history,
            company_domain_norm=company_domain_norm or None,
            company_name_norm=company_name_norm or None,
            email_norm=email_norm,
        )
    )
    db.commit()

    return {"ok": True, "job_id": str(job_id), "emails": emails, "history": "inserted"}
