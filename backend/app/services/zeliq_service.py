from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.models import LinkupEmailCache, ProviderLog, ZeliqEnrichmentJob
from app.services.normalization import extract_emails, is_valid_email, normalize_domain


@dataclass
class ZeliqEmailRequestResult:
    job_id: uuid.UUID
    emails: list[str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_emails_any(payload: object) -> list[str]:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    emails = extract_emails(text)
    out: list[str] = []
    seen: set[str] = set()
    for e in emails:
        e2 = (e or "").strip().lower()
        if not e2 or not is_valid_email(e2) or e2 in seen:
            continue
        seen.add(e2)
        out.append(e2)
    return out


class ZeliqService:
    BASE_URL = "https://api.zeliq.com"

    def __init__(self, *, db: Session, run_id: uuid.UUID) -> None:
        self._db = db
        self._run_id = run_id
        self._settings = Settings()

        self._queried_emails: set[tuple[str, str]] = set()

    @property
    def is_configured(self) -> bool:
        return bool(
            self._settings.zeliq_api_key
            and self._settings.zeliq_callback_base_url
            and self._settings.zeliq_webhook_secret
        )

    def build_callback_url(self, *, job_id: uuid.UUID, kind: str) -> str:
        base = (self._settings.zeliq_callback_base_url or "").rstrip("/")
        secret = self._settings.zeliq_webhook_secret or ""
        return f"{base}/api/integrations/zeliq/callback/{kind}?job_id={job_id}&secret={secret}"

    def _redact_callback_url(self, url: str) -> str:
        if not url:
            return url
        # Keep it simple: strip the secret query param value.
        return url.replace(f"secret={self._settings.zeliq_webhook_secret}", "secret=REDACTED")

    def _log(self, *, kind: str, key: str | None, request: dict, response: dict) -> None:
        try:
            self._db.add(
                ProviderLog(
                    run_id=self._run_id,
                    provider="zeliq",
                    kind=kind,
                    key=key,
                    request=request,
                    response=response,
                )
            )
            self._db.commit()
        except Exception:  # pragma: no cover
            self._db.rollback()

    def request_email_enrichment(
        self,
        *,
        person_key: str,
        company_domain: str,
        company_name: str | None,
        first_name: str | None,
        last_name: str | None,
        linkedin_url: str | None,
    ) -> ZeliqEmailRequestResult | None:
        domain_norm = normalize_domain(company_domain)
        if not domain_norm:
            return None

        key = (person_key, domain_norm)
        if key in self._queried_emails:
            return None
        self._queried_emails.add(key)

        if not self.is_configured:
            return None

        job_id = uuid.uuid4()
        callback_url = self.build_callback_url(job_id=job_id, kind="email")

        payload_to_send = {
            "first_name": (first_name or "").strip(),
            "last_name": (last_name or "").strip(),
            "company": domain_norm or (company_name or ""),
            "linkedin_url": (linkedin_url or "").strip(),
            "callback_url": callback_url,
        }
        payload_to_store = dict(payload_to_send)
        payload_to_store["callback_url"] = self._redact_callback_url(callback_url)
        payload_to_store["company_domain"] = domain_norm
        payload_to_store["company_name"] = (company_name or "").strip()

        job = ZeliqEnrichmentJob(
            job_id=job_id,
            kind="email",
            status="pending",
            person_key=person_key,
            company_domain_norm=domain_norm,
            run_id=self._run_id,
            request_payload=payload_to_store,
            response_payload=None,
            created_at=_now(),
            updated_at=_now(),
        )
        self._db.add(job)
        self._db.commit()

        try:
            resp = httpx.post(
                f"{self.BASE_URL}/api/contact/enrich/email",
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "x-api-key": str(self._settings.zeliq_api_key),
                },
                json=payload_to_send,
                timeout=30,
            )
            resp.raise_for_status()
            content_type = (resp.headers.get("content-type") or "").lower()
            if "application/json" in content_type:
                data: object = resp.json()
            else:
                data = {"text": resp.text}
        except Exception as e:
            job.status = "error"
            job.response_payload = {"error": str(e)}
            job.updated_at = _now()
            self._db.add(job)
            self._db.commit()
            self._log(
                kind="email_enrich",
                key=str(job_id),
                request=payload_to_store,
                response={"error": str(e)},
            )
            raise

        emails = _extract_emails_any(data)

        job.response_payload = data if isinstance(data, dict) else {"data": data}
        job.updated_at = _now()
        if emails:
            job.status = "completed"
            self._upsert_email_cache(person_key=person_key, company_domain_norm=domain_norm, emails=emails, evidence="zeliq")
        else:
            job.status = "requested"

        self._db.add(job)
        self._db.commit()

        self._log(
            kind="email_enrich",
            key=str(job_id),
            request=payload_to_store,
            response={"raw": data if isinstance(data, dict) else {"data": data}, "extracted_emails": emails},
        )

        return ZeliqEmailRequestResult(job_id=job_id, emails=emails)

    def handle_email_callback(self, *, job_id: uuid.UUID, payload: object) -> list[str]:
        job = self._db.execute(select(ZeliqEnrichmentJob).where(ZeliqEnrichmentJob.job_id == job_id)).scalar_one_or_none()
        if job is None:
            raise KeyError("unknown job_id")

        emails = _extract_emails_any(payload)

        job.response_payload = payload if isinstance(payload, dict) else {"data": payload}
        job.updated_at = _now()
        job.status = "completed" if emails else "completed_empty"
        self._db.add(job)

        if emails:
            self._upsert_email_cache(
                person_key=job.person_key,
                company_domain_norm=job.company_domain_norm,
                emails=emails,
                evidence="zeliq_callback",
            )

        self._db.commit()
        self._log(
            kind="email_callback",
            key=str(job_id),
            request={"job_id": str(job_id)},
            response={"raw": payload if isinstance(payload, dict) else {"data": payload}, "extracted_emails": emails},
        )
        return emails

    def _upsert_email_cache(self, *, person_key: str, company_domain_norm: str, emails: list[str], evidence: str) -> None:
        now = _now()
        expires_at = now + timedelta(days=30)

        existing = self._db.execute(
            select(LinkupEmailCache).where(
                LinkupEmailCache.person_key == person_key,
                LinkupEmailCache.company_domain_norm == company_domain_norm,
            )
        ).scalar_one_or_none()

        if existing is None:
            self._db.add(
                LinkupEmailCache(
                    person_key=person_key,
                    company_domain_norm=company_domain_norm,
                    response={"emails": emails, "evidence_text": evidence},
                    fetched_at=now,
                    expires_at=expires_at,
                )
            )
            return

        current = existing.response.get("emails") if isinstance(existing.response, dict) else None
        current_list = current if isinstance(current, list) else []
        merged: list[str] = []
        seen: set[str] = set()
        for e in [*current_list, *emails]:
            e2 = (e or "").strip().lower()
            if not e2 or not is_valid_email(e2) or e2 in seen:
                continue
            seen.add(e2)
            merged.append(e2)

        existing.response = {"emails": merged, "evidence_text": evidence}
        existing.fetched_at = now
        existing.expires_at = expires_at
        self._db.add(existing)
