from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.models import BlacklistEntry, Config, History, LinkupEmailCache, RunLog
from app.services.blacklist import Blacklist
from app.services.graph_service import GraphClient
from app.services.history_index import HistoryIndex, name_person_key, person_key
from app.services.linkup_service import EffectiveConfig, LinkupService
from app.services.normalization import domain_matches, normalize_company_name, normalize_domain, normalize_person_name
from app.services.targeting import Contact, select_target_contacts
from app.services.templates import render_template
from app.services.zeliq_service import ZeliqService


@dataclass
class RunSummary:
    run_id: uuid.UUID
    created_drafts: int
    quota: int
    excluded_count: int
    enrich_failed_count: int
    pool_exhausted: bool
    errors: list[dict]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _wait_for_cached_emails(
    *,
    db: Session,
    person_key: str,
    company_domain_norm: str,
    timeout_seconds: int,
) -> list[str]:
    if timeout_seconds <= 0:
        return []

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        now = _now()
        cached = db.execute(
            select(LinkupEmailCache).where(
                LinkupEmailCache.person_key == person_key,
                LinkupEmailCache.company_domain_norm == company_domain_norm,
                LinkupEmailCache.expires_at > now,
            )
        ).scalar_one_or_none()
        if cached and isinstance(cached.response, dict):
            raw = cached.response.get("emails")
            emails = raw if isinstance(raw, list) else []
            valid = [e.strip().lower() for e in emails if isinstance(e, str) and "@" in e]
            if valid:
                return valid
        time.sleep(1)

    return []


def _choose_best_email(
    *,
    emails: list[str],
    first_name: str | None,
    last_name: str | None,
    company_domain_norm: str,
) -> str | None:
    if not emails:
        return None

    fn = normalize_person_name(first_name).replace(" ", "")
    ln = normalize_person_name(last_name).replace(" ", "")

    scored: list[tuple[tuple[int, int], str]] = []
    for e in emails:
        e2 = (e or "").strip().lower()
        if "@" not in e2:
            continue
        local, dom = e2.split("@", 1)
        dom_norm = normalize_domain(dom)
        domain_score = 1 if domain_matches(dom_norm, company_domain_norm) else 0

        local_simple = normalize_person_name(local).replace(" ", "")
        name_score = 0
        if fn and ln and fn in local_simple and ln in local_simple:
            name_score = 2
        elif ln and ln in local_simple:
            name_score = 1
        scored.append(((domain_score, name_score), e2))

    if not scored:
        return emails[0].strip().lower()
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[0][1]


def run_daily_iter(
    *,
    db: Session,
    dry_run: bool,
    overrides: dict | None,
) -> Iterator[dict]:
    run_id = uuid.uuid4()
    started_at = _now()

    config = db.execute(select(Config).where(Config.id == 1)).scalar_one_or_none()
    if config is None:
        config = Config(id=1)
        db.add(config)
        db.commit()

    effective = {
        "industry": config.industry,
        "location": config.location,
        "company_size_min": config.company_size_min,
        "daily_objective": config.daily_objective,
        "email_subject_template": config.email_subject_template,
        "email_body_template": config.email_body_template,
        "alert_email": config.alert_email,
        "run_mode": config.run_mode,
    }
    if overrides:
        for k, v in overrides.items():
            if v is not None and k in effective:
                effective[k] = v

    run_mode = "dry_run" if dry_run else str(effective["run_mode"])
    quota = int(effective["daily_objective"])

    run_log = RunLog(
        run_id=run_id,
        started_at=started_at,
        quota=quota,
        created_drafts=0,
        excluded_count=0,
        enrich_failed_count=0,
        pool_exhausted=False,
        errors={},
        run_mode=run_mode,
        overrides=overrides or {},
    )
    db.add(run_log)
    db.commit()

    yield {
        "type": "start",
        "run_id": str(run_id),
        "started_at": started_at.isoformat(),
        "quota": quota,
        "run_mode": run_mode,
    }

    blacklist_rows = db.execute(select(BlacklistEntry)).scalars().all()
    bl_domains = [r.value_norm for r in blacklist_rows if r.entry_type == "domain"]
    bl_names = [r.value_norm for r in blacklist_rows if r.entry_type == "company_name"]
    blacklist = Blacklist.from_values(company_names_norm=bl_names, domains_norm=bl_domains)

    history_rows = [
        {
            "company_domain": h.company_domain,
            "company_domain_norm": h.company_domain_norm,
            "company_name": h.company_name,
            "company_name_norm": h.company_name_norm,
            "employee_count": h.employee_count,
            "first_name": h.first_name,
            "last_name": h.last_name,
            "email": h.email,
            "email_norm": h.email_norm,
        }
        for h in db.execute(select(History)).scalars().all()
    ]
    history = HistoryIndex.build(history_rows)

    settings = Settings()
    linkup = LinkupService(db=db, run_id=run_id)
    zeliq = ZeliqService(db=db, run_id=run_id)
    graph = GraphClient()

    enrich_provider = (settings.email_enrich_provider or "linkup").strip().lower()
    zeliq_enabled = enrich_provider == "zeliq"
    if zeliq_enabled and not zeliq.is_configured:
        zeliq_enabled = False
    zeliq_wait_seconds = max(0, int(settings.zeliq_wait_seconds or 0))

    created_drafts = 0
    excluded_count = 0
    enrich_failed_count = 0
    errors: list[dict] = []
    pool_exhausted = False

    attempted_companies: set[str] = set()
    attempted_people: set[str] = set()

    action_count = 0
    companies_total = 0
    companies_seen = 0
    contacts_tried = 0
    contact_searches = 0

    def persist_run_log() -> None:
        run_log.created_drafts = created_drafts
        run_log.excluded_count = excluded_count
        run_log.enrich_failed_count = enrich_failed_count
        run_log.pool_exhausted = pool_exhausted
        db.add(run_log)
        db.commit()

    def emit_progress(last: dict) -> None:
        nonlocal action_count
        action_count += 1
        if action_count % 3 == 0:
            persist_run_log()
        yield_event = {
            "type": "progress",
            "run_id": str(run_id),
            "created_drafts": created_drafts,
            "quota": quota,
            "excluded_count": excluded_count,
            "enrich_failed_count": enrich_failed_count,
            "pool_exhausted": pool_exhausted,
            "companies_total": companies_total,
            "companies_seen": companies_seen,
            "contacts_tried": contacts_tried,
            "contact_searches": contact_searches,
            "last": last,
        }
        return yield_event

    def emit_info(*, message: str, company_name: str | None = None, company_domain: str | None = None) -> dict:
        return emit_progress(
            {
                "date_time": _now().isoformat(),
                "company_name": company_name,
                "company_domain": company_domain,
                "employee_count": None,
                "first_name": None,
                "last_name": None,
                "email": None,
                "job_title": None,
                "status_code": "INFO",
                "status_detail": message,
            }
        )

    def write_history(
        *,
        company_name: str | None,
        company_domain: str | None,
        employee_count: int | None,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        job_title: str | None,
        status_code: str,
        status_detail: str | None = None,
    ) -> dict:
        nonlocal history

        domain_norm = normalize_domain(company_domain)
        name_norm = normalize_company_name(company_name)
        email_norm = (email or "").strip().lower() or None
        row = History(
            date_time=_now(),
            company_name=company_name,
            company_domain=company_domain,
            employee_count=employee_count,
            first_name=first_name,
            last_name=last_name,
            email=email,
            job_title=job_title,
            status_code=status_code,
            status_detail=status_detail,
            run_id=run_id,
            company_domain_norm=domain_norm or None,
            company_name_norm=name_norm or None,
            email_norm=email_norm,
        )
        db.add(row)
        db.commit()

        pk = person_key(email=email_norm, first_name=first_name, last_name=last_name, company_domain_norm=domain_norm)
        if pk:
            history.add_person(pk)
        npk = name_person_key(first_name=first_name, last_name=last_name, company_domain_norm=domain_norm)
        if npk:
            history.add_person(npk)

        return {
            "date_time": row.date_time.isoformat(),
            "company_name": company_name,
            "company_domain": company_domain,
            "employee_count": employee_count,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "job_title": job_title,
            "status_code": status_code,
            "status_detail": status_detail,
        }

    companies = linkup.search_companies(
        EffectiveConfig(
            industry=str(effective["industry"]),
            location=str(effective["location"]),
            company_size_min=int(effective["company_size_min"]),
            daily_objective=quota,
        )
    )
    companies_total = len(companies)
    company_iter = iter(companies)

    while created_drafts < quota:
        try:
            company = next(company_iter)
        except StopIteration:
            pool_exhausted = True
            last = write_history(
                company_name=None,
                company_domain=None,
                employee_count=None,
                first_name=None,
                last_name=None,
                email=None,
                job_title=None,
                status_code="POOL_EXHAUSTED",
                status_detail=(
                    f"created={created_drafts} quota={quota} companies_total={companies_total} companies_seen={companies_seen}"
                ),
            )
            yield emit_progress(last)
            break

        company_name = company.company_name
        company_domain = normalize_domain(company.company_domain)
        employee_count = company.employee_count
        companies_seen += 1

        if not company_name or not company_domain:
            enrich_failed_count += 1
            last = write_history(
                company_name=company_name,
                company_domain=company_domain,
                employee_count=employee_count,
                first_name=None,
                last_name=None,
                email=None,
                job_title=None,
                status_code="ENRICH_FAILED",
                status_detail="missing company name/domain",
            )
            yield emit_progress(last)
            continue

        company_name_norm = normalize_company_name(company_name)
        company_domain_norm = company_domain
        company_key = f"{company_domain_norm}|{company_name_norm}"

        if company_key in attempted_companies:
            excluded_count += 1
            last = write_history(
                company_name=company_name,
                company_domain=company_domain,
                employee_count=employee_count,
                first_name=None,
                last_name=None,
                email=None,
                job_title=None,
                status_code="DUPLICATE_PERSON_BLOCKED",
                status_detail="company already attempted in this run",
            )
            yield emit_progress(last)
            continue
        attempted_companies.add(company_key)

        is_blacklisted, matched_detail = blacklist.match(company_name=company_name_norm, company_domain=company_domain)
        if is_blacklisted:
            excluded_count += 1
            last = write_history(
                company_name=company_name,
                company_domain=company_domain,
                employee_count=employee_count,
                first_name=None,
                last_name=None,
                email=None,
                job_title=None,
                status_code="EXCLUDED_BLACKLIST",
                status_detail=matched_detail,
            )
            yield emit_progress(last)
            continue

        company_in_history = history.company_exists(company_domain_norm=company_domain_norm, company_name_norm=company_name_norm)
        if company_in_history and (employee_count is None or employee_count < 200):
            excluded_count += 1
            last = write_history(
                company_name=company_name,
                company_domain=company_domain,
                employee_count=employee_count,
                first_name=None,
                last_name=None,
                email=None,
                job_title=None,
                status_code="EXCLUDED_HISTORY_SMB",
                status_detail="company seen before and employee_count < 200",
            )
            yield emit_progress(last)
            continue

        max_contact_searches = max(1, int(settings.linkup_contact_search_attempts_per_company or 1))
        company_made_progress = False

        for attempt in range(max_contact_searches):
            if created_drafts >= quota:
                break

            contact_searches += 1
            yield emit_info(
                message=f"Contact search attempt {attempt + 1}/{max_contact_searches}",
                company_name=company_name,
                company_domain=company_domain,
            )

            try:
                contacts_raw = linkup.get_contacts(
                    company_name=company_name,
                    company_domain=company_domain,
                    employee_count=employee_count,
                    force_refresh=attempt > 0,
                    query_variant=attempt,
                )
            except Exception as e:  # pragma: no cover
                errors.append({"type": "LINKUP_CONTACTS", "detail": str(e)})
                excluded_count += 1
                last = write_history(
                    company_name=company_name,
                    company_domain=company_domain,
                    employee_count=employee_count,
                    first_name=None,
                    last_name=None,
                    email=None,
                    job_title=None,
                    status_code="ERROR_LINKUP",
                    status_detail=str(e),
                )
                yield emit_progress(last)
                break

            contacts = [
                Contact(
                    first_name=c.first_name,
                    last_name=c.last_name,
                    job_title=c.job_title,
                    email=c.email,
                    profile_url=c.profile_url,
                )
                for c in contacts_raw
            ]
            targets = select_target_contacts(contacts, employee_count)

            if not targets:
                if attempt < max_contact_searches - 1:
                    yield emit_info(
                        message="No matching target contacts; retrying with a broader search",
                        company_name=company_name,
                        company_domain=company_domain,
                    )
                    continue
                enrich_failed_count += 1
                last = write_history(
                    company_name=company_name,
                    company_domain=company_domain,
                    employee_count=employee_count,
                    first_name=None,
                    last_name=None,
                    email=None,
                    job_title=None,
                    status_code="ENRICH_FAILED",
                    status_detail="no matching target contacts",
                )
                yield emit_progress(last)
                break

            # Try each target contact for this company. If all fail, we will re-query Linkup
            # for additional contacts (bounded by max_contact_searches).
            any_ready_for_company_attempt = False
            for c in targets:
                if created_drafts >= quota:
                    break

                contacts_tried += 1

                if not c.email and (not c.first_name or not c.last_name):
                    enrich_failed_count += 1
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=None,
                        job_title=c.job_title,
                        status_code="ENRICH_FAILED",
                        status_detail="missing first_name/last_name (and no email)",
                    )
                    yield emit_progress(last)
                    continue

                pk = person_key(
                    email=c.email,
                    first_name=c.first_name,
                    last_name=c.last_name,
                    company_domain_norm=company_domain_norm,
                )
                if not pk:
                    enrich_failed_count += 1
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=None,
                        job_title=c.job_title,
                        status_code="ENRICH_FAILED",
                        status_detail="could not compute person identity",
                    )
                    yield emit_progress(last)
                    continue

                if pk in attempted_people:
                    excluded_count += 1
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=c.email,
                        job_title=c.job_title,
                        status_code="DUPLICATE_PERSON_BLOCKED",
                        status_detail="duplicate within run",
                    )
                    yield emit_progress(last)
                    continue
                attempted_people.add(pk)

                if history.person_exists(pk):
                    excluded_count += 1
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=c.email,
                        job_title=c.job_title,
                        status_code="DUPLICATE_PERSON_BLOCKED",
                        status_detail="duplicate in history",
                    )
                    yield emit_progress(last)
                    continue

                emails: list[str] = []
                if c.email:
                    emails.append(c.email.strip().lower())

                try:
                    if zeliq_enabled:
                        zres = zeliq.request_email_enrichment(
                            person_key=pk,
                            company_domain=company_domain,
                            company_name=company_name,
                            first_name=c.first_name,
                            last_name=c.last_name,
                            linkedin_url=c.profile_url,
                        )
                        if zres:
                            emails.extend(zres.emails)
                            if not zres.emails and zeliq_wait_seconds > 0:
                                emails.extend(
                                    _wait_for_cached_emails(
                                        db=db,
                                        person_key=pk,
                                        company_domain_norm=company_domain_norm,
                                        timeout_seconds=zeliq_wait_seconds,
                                    )
                                )
                    else:
                        emails.extend(
                            linkup.enrich_email(
                                person_key=pk,
                                company_domain=company_domain,
                                company_name=company_name,
                                first_name=c.first_name,
                                last_name=c.last_name,
                            )
                        )
                except Exception as e:  # pragma: no cover
                    errors.append(
                        {
                            "type": "ZELIQ_ENRICH" if zeliq_enabled else "LINKUP_ENRICH",
                            "detail": str(e),
                        }
                    )
                    enrich_failed_count += 1
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=None,
                        job_title=c.job_title,
                        status_code="ERROR_ZELIQ" if zeliq_enabled else "ERROR_LINKUP",
                        status_detail=str(e),
                    )
                    yield emit_progress(last)
                    continue

                best = _choose_best_email(
                    emails=list(dict.fromkeys([e for e in emails if e])),
                    first_name=c.first_name,
                    last_name=c.last_name,
                    company_domain_norm=company_domain_norm,
                )
                if not best:
                    enrich_failed_count += 1
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=None,
                        job_title=c.job_title,
                        status_code="ENRICH_FAILED",
                        status_detail="no email found",
                    )
                    yield emit_progress(last)
                    continue

                best_domain = best.split("@")[-1].strip().lower()
                if not domain_matches(best_domain, company_domain_norm):
                    enrich_failed_count += 1
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=best,
                        job_title=c.job_title,
                        status_code="ENRICH_FAILED",
                        status_detail=f"email domain mismatch: {best_domain} != {company_domain_norm}",
                    )
                    yield emit_progress(last)
                    continue

                subject = render_template(
                    str(effective["email_subject_template"]),
                    first_name=c.first_name,
                    company=company_name,
                )
                body = render_template(
                    str(effective["email_body_template"]),
                    first_name=c.first_name,
                    company=company_name,
                )

                if run_mode == "dry_run" or not graph.is_configured:
                    created_drafts += 1
                    any_ready_for_company_attempt = True
                    company_made_progress = True
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=best,
                        job_title=c.job_title,
                        status_code="DRY_RUN_READY",
                        status_detail=subject,
                    )
                    yield emit_progress(last)
                    continue

                try:
                    draft = graph.create_draft(to_email=best, subject=subject, body=body)
                    created_drafts += 1
                    any_ready_for_company_attempt = True
                    company_made_progress = True
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=best,
                        job_title=c.job_title,
                        status_code="DRAFT_CREATED",
                        status_detail=draft.message_id,
                    )
                    yield emit_progress(last)
                except Exception as e:
                    errors.append({"type": "GRAPH", "detail": str(e)})
                    last = write_history(
                        company_name=company_name,
                        company_domain=company_domain,
                        employee_count=employee_count,
                        first_name=c.first_name,
                        last_name=c.last_name,
                        email=best,
                        job_title=c.job_title,
                        status_code="ERROR_GRAPH",
                        status_detail=str(e),
                    )
                    yield emit_progress(last)

            # If we couldn't produce any draft-ready contact from this attempt, re-query Linkup for more contacts.
            if not any_ready_for_company_attempt and attempt < max_contact_searches - 1 and created_drafts < quota:
                yield emit_info(
                    message="No usable email found for target contacts; retrying contact search",
                    company_name=company_name,
                    company_domain=company_domain,
                )

            if any_ready_for_company_attempt:
                break

        if not company_made_progress and created_drafts < quota:
            # Not an error; this company just didn't yield any usable email/draft after retries.
            yield emit_info(
                message=f"No draft created for this company after {max_contact_searches} contact searches",
                company_name=company_name,
                company_domain=company_domain,
            )

    finished_at = _now()
    run_log.created_drafts = created_drafts
    run_log.excluded_count = excluded_count
    run_log.enrich_failed_count = enrich_failed_count
    run_log.pool_exhausted = pool_exhausted
    run_log.finished_at = finished_at
    run_log.errors = {"items": errors}
    db.add(run_log)
    db.commit()

    yield {
        "type": "done",
        "run_id": str(run_id),
        "created_drafts": created_drafts,
        "quota": quota,
        "excluded_count": excluded_count,
        "enrich_failed_count": enrich_failed_count,
        "pool_exhausted": pool_exhausted,
        "errors": errors,
        "finished_at": finished_at.isoformat(),
    }


def run_daily(
    *,
    db: Session,
    dry_run: bool,
    overrides: dict | None,
) -> RunSummary:
    done: dict | None = None
    for ev in run_daily_iter(db=db, dry_run=dry_run, overrides=overrides):
        if ev.get("type") == "done":
            done = ev
    if not done:
        raise RuntimeError("Run did not produce summary")
    return RunSummary(
        run_id=uuid.UUID(done["run_id"]),
        created_drafts=int(done["created_drafts"]),
        quota=int(done["quota"]),
        excluded_count=int(done["excluded_count"]),
        enrich_failed_count=int(done["enrich_failed_count"]),
        pool_exhausted=bool(done["pool_exhausted"]),
        errors=list(done.get("errors") or []),
    )
