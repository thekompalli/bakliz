from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.models import LinkupCompanySearchCache, LinkupContactsCache, LinkupEmailCache, ProviderLog
from app.services.normalization import extract_emails, is_valid_email, normalize_domain

try:
    from linkup import LinkupClient
except Exception:  # pragma: no cover
    LinkupClient = None  # type: ignore[assignment]


class CompanyItem(BaseModel):
    company_name: str
    company_domain: str
    employee_count: int | None = None
    hq_location: str | None = None
    hq_country: str | None = None


class CompanySearchOutput(BaseModel):
    companies: list[CompanyItem] = Field(default_factory=list)

    @field_validator("companies", mode="before")
    @classmethod
    def _coerce_companies(cls, v):  # noqa: ANN001
        return [] if v is None else v


class ContactItem(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    email: str | None = None
    profile_url: str | None = None


class ContactsOutput(BaseModel):
    contacts: list[ContactItem] = Field(default_factory=list)

    @field_validator("contacts", mode="before")
    @classmethod
    def _coerce_contacts(cls, v):  # noqa: ANN001
        return [] if v is None else v


class EmailEnrichmentOutput(BaseModel):
    emails: list[str] = Field(default_factory=list)
    evidence_text: str | None = None

    @field_validator("emails", mode="before")
    @classmethod
    def _coerce_emails(cls, v):  # noqa: ANN001
        return [] if v is None else v


@dataclass
class EffectiveConfig:
    industry: str
    location: str
    company_size_min: int
    daily_objective: int


class LinkupService:
    def __init__(self, *, db: Session, run_id: uuid.UUID) -> None:
        self._db = db
        self._run_id = run_id
        self._settings = Settings()
        self._client: LinkupClient | None = None

        self._queried_company_search = False
        self._queried_contacts: set[tuple[str, int]] = set()
        self._queried_emails: set[tuple[str, str]] = set()

        if self._settings.linkup_api_key and not self._settings.bakliz_demo_mode:
            if LinkupClient is None:  # pragma: no cover
                raise RuntimeError("linkup-sdk is not installed")
            self._client = LinkupClient(api_key=self._settings.linkup_api_key)

    @property
    def is_demo(self) -> bool:
        return self._client is None

    def _log(self, *, kind: str, key: str | None, request: dict, response: dict) -> None:
        try:
            self._db.add(
                ProviderLog(
                    run_id=self._run_id,
                    provider="linkup",
                    kind=kind,
                    key=key,
                    request=request,
                    response=response,
                )
            )
            self._db.commit()
        except Exception:  # pragma: no cover
            self._db.rollback()

    def search_companies(self, cfg: EffectiveConfig) -> list[CompanyItem]:
        today = date.today()
        cache_key = f"{cfg.industry}|{cfg.location}|{cfg.company_size_min}|{today.isoformat()}"
        cached = self._db.execute(
            select(LinkupCompanySearchCache).where(
                LinkupCompanySearchCache.industry == cfg.industry,
                LinkupCompanySearchCache.location == cfg.location,
                LinkupCompanySearchCache.company_size_min == cfg.company_size_min,
                LinkupCompanySearchCache.query_date == today,
            )
        ).scalar_one_or_none()

        if cached is not None:
            self._log(
                kind="company_search",
                key=cache_key,
                request={
                    "industry": cfg.industry,
                    "location": cfg.location,
                    "company_size_min": cfg.company_size_min,
                    "query_date": today.isoformat(),
                    "cache_hit": True,
                },
                response=cached.response,
            )
            return CompanySearchOutput.model_validate(cached.response).companies

        if self.is_demo:
            companies = _demo_companies(cfg)
            self._log(
                kind="company_search",
                key=cache_key,
                request={
                    "industry": cfg.industry,
                    "location": cfg.location,
                    "company_size_min": cfg.company_size_min,
                    "query_date": today.isoformat(),
                    "demo": True,
                },
                response=CompanySearchOutput(companies=companies).model_dump(),
            )
            self._db.add(
                LinkupCompanySearchCache(
                    industry=cfg.industry,
                    location=cfg.location,
                    company_size_min=cfg.company_size_min,
                    query_date=today,
                    response=CompanySearchOutput(companies=companies).model_dump(),
                )
            )
            self._db.commit()
            return companies

        # Real Linkup search (structured output)
        if self._queried_company_search:
            return []
        self._queried_company_search = True

        query = (
            "Find companies that match:\n"
            f"- Industry: {cfg.industry}\n"
            f"- Location (HQ, strict): {cfg.location}\n"
            f"- Minimum employees: {cfg.company_size_min}\n\n"
            "Return up to 50 companies with:\n"
            "- company_name\n"
            "- company_domain (root domain)\n"
            "- employee_count (integer if available)\n"
            "- hq_location (city/region if known)\n"
            "- hq_country (country if known)\n"
            "\nIMPORTANT:\n"
            f"- Only include companies headquartered in {cfg.location}.\n"
            "- Do NOT include companies just operating/hiring there.\n"
        )

        assert self._client is not None
        result: CompanySearchOutput = self._client.search(
            query=query,
            depth="standard",
            output_type="structured",
            structured_output_schema=CompanySearchOutput,
            max_results=200,
            include_sources=False,
        )

        companies = [
            c
            for c in result.companies
            if c.company_name and normalize_domain(c.company_domain) and (c.employee_count is None or c.employee_count >= 0)
        ]

        # Post-filter for location to reduce irrelevant geos (e.g., Italy config returning India results).
        loc = (cfg.location or "").strip().lower()
        if loc:
            filtered: list[CompanyItem] = []
            for c in companies:
                hq = (c.hq_location or "").strip().lower()
                country = (c.hq_country or "").strip().lower()
                if hq and loc in hq:
                    filtered.append(c)
                    continue
                if country and loc in country:
                    filtered.append(c)
                    continue
                # Heuristic fallback: allow matching ccTLD for common country names.
                dom = normalize_domain(c.company_domain)
                if loc == "italy" and dom.endswith(".it"):
                    filtered.append(c)
                    continue
            companies = filtered

        self._log(
            kind="company_search",
            key=cache_key,
            request={
                "query": query,
                "industry": cfg.industry,
                "location": cfg.location,
                "company_size_min": cfg.company_size_min,
                "query_date": today.isoformat(),
                "cache_hit": False,
            },
            response={
                "raw": result.model_dump(),
                "post_filtered": CompanySearchOutput(companies=companies).model_dump(),
            },
        )

        self._db.add(
            LinkupCompanySearchCache(
                industry=cfg.industry,
                location=cfg.location,
                company_size_min=cfg.company_size_min,
                query_date=today,
                response=CompanySearchOutput(companies=companies).model_dump(),
            )
        )
        self._db.commit()
        return companies

    def get_contacts(
        self,
        *,
        company_name: str,
        company_domain: str,
        employee_count: int | None,
        force_refresh: bool = False,
        query_variant: int = 0,
    ) -> list[ContactItem]:
        domain_norm = normalize_domain(company_domain)
        now = datetime.now(timezone.utc)

        cached = self._db.execute(
            select(LinkupContactsCache).where(
                LinkupContactsCache.company_domain_norm == domain_norm,
                LinkupContactsCache.expires_at > now,
            )
        ).scalar_one_or_none()
        if cached is not None and not force_refresh:
            self._log(
                kind="contacts",
                key=domain_norm,
                request={
                    "company_name": company_name,
                    "company_domain": domain_norm,
                    "employee_count": employee_count,
                    "cache_hit": True,
                    "force_refresh": False,
                    "query_variant": int(query_variant),
                },
                response=cached.response,
            )
            return ContactsOutput.model_validate(cached.response).contacts

        existing = self._db.execute(
            select(LinkupContactsCache).where(LinkupContactsCache.company_domain_norm == domain_norm)
        ).scalar_one_or_none()

        if self.is_demo:
            contacts = _demo_contacts(company_domain=domain_norm, employee_count=employee_count)
            self._log(
                kind="contacts",
                key=domain_norm,
                request={
                    "company_name": company_name,
                    "company_domain": domain_norm,
                    "employee_count": employee_count,
                    "demo": True,
                    "force_refresh": bool(force_refresh),
                    "query_variant": int(query_variant),
                },
                response=ContactsOutput(contacts=contacts).model_dump(),
            )
            if existing is None:
                self._db.add(
                    LinkupContactsCache(
                        company_domain_norm=domain_norm,
                        response=ContactsOutput(contacts=contacts).model_dump(),
                        fetched_at=now,
                        expires_at=now + timedelta(days=30),
                    )
                )
            else:
                existing.response = ContactsOutput(contacts=contacts).model_dump()
                existing.fetched_at = now
                existing.expires_at = now + timedelta(days=30)
                self._db.add(existing)
            self._db.commit()
            return contacts

        key = (domain_norm, int(query_variant))
        if key in self._queried_contacts:
            return []
        self._queried_contacts.add(key)

        is_key_account = employee_count is not None and employee_count >= 200
        if is_key_account:
            target_hint = (
                "Focus ONLY on these departments/titles (English + French), ideally 1-2 per category:\n"
                "- Procurement/Purchasing: Procurement, Purchasing, Acheteur, Directeur Achats, Responsable Achats\n"
                "- Fleet/Mobility/General Services: Fleet Manager, Mobility Manager, Responsable Parc Auto, Responsable Mobilité, Services Généraux\n"
                "- CSR/ESG/Sustainability: CSR, ESG, Sustainability, RSE, Développement Durable\n"
            )
        else:
            target_hint = (
                "Focus ONLY on these titles (English + French), ideally 1 per category:\n"
                "- CEO/Owner: CEO, Founder, President, Owner, Directeur Général, PDG, Gérant\n"
                "- CFO/Finance: CFO, Finance Director, Head of Finance, Directeur Financier, DAF\n"
                "- Fleet/General Services: Fleet Manager, Mobility Manager, Responsable Parc Auto, Responsable Mobilité, Services Généraux\n"
            )

        # Override: always prioritize top executives (CEO/COO/CTO or other C-level chiefs).
        target_hint = (
            "Focus ONLY on top executives / C-level leadership (English + French + Italian), ideally 1 per role:\n"
            "- CEO/President/Managing Director: CEO, Chief Executive Officer, President, Managing Director, Directeur Général, PDG, Gérant, Amministratore Delegato, Direttore Generale\n"
            "- COO/Operations: COO, Chief Operating Officer, Head of Operations, Operations Director, Directeur des Opérations, Direttore Operativo\n"
            "- CTO/Technology: CTO, Chief Technology Officer, Head of Technology, Head of Engineering, Directeur Technique, Direttore Tecnico\n"
            "- If a role is missing, include other C-level (CIO/CISO/Chief of Staff) as fallback.\n"
            "\nIMPORTANT:\n"
            "- Prefer contacts with a LinkedIn or official profile URL that clearly belongs to the company.\n"
            "- Do NOT invent titles.\n"
        )

        base_query = (
            f"Find decision makers at {company_name} ({domain_norm}).\n"
            f"{target_hint}\n"
            "Return up to 30 contacts with:\n"
            "- first_name\n"
            "- last_name\n"
            "- job_title\n"
            "- email (ONLY if publicly listed)\n"
            "- profile_url (LinkedIn or company page if available)\n"
        )

        # Variants are intentionally different to allow a bounded retry loop.
        # They ask for slightly different evidence sources and phrasing to reduce repeated/stale results.
        if int(query_variant) <= 0:
            query = base_query
        elif int(query_variant) == 1:
            query = (
                base_query
                + "\n\nIf you cannot find enough target contacts:\n"
                "- Use LinkedIn pages and leadership/team pages.\n"
                "- Prefer contacts whose profile explicitly mentions the company.\n"
            )
        else:
            query = (
                base_query
                + "\n\nIf results are still sparse, broaden slightly:\n"
                "- Include close title variants within the same departments.\n"
                "- Include country-language variants and abbreviations.\n"
                "- Still return real people (no generic inboxes).\n"
            )

        assert self._client is not None
        result: ContactsOutput = self._client.search(
            query=query,
            depth="standard",
            output_type="structured",
            structured_output_schema=ContactsOutput,
            max_results=30,
            include_sources=False,
        )

        contacts: list[ContactItem] = []
        for c in result.contacts:
            if c.email and not is_valid_email(c.email):
                c.email = None
            contacts.append(c)

        if existing is None:
            self._db.add(
                LinkupContactsCache(
                    company_domain_norm=domain_norm,
                    response=ContactsOutput(contacts=contacts).model_dump(),
                    fetched_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
        else:
            existing.response = ContactsOutput(contacts=contacts).model_dump()
            existing.fetched_at = now
            existing.expires_at = now + timedelta(days=30)
            self._db.add(existing)
        self._db.commit()

        self._log(
            kind="contacts",
            key=domain_norm,
            request={
                "query": query,
                "company_name": company_name,
                "company_domain": domain_norm,
                "employee_count": employee_count,
                "cache_hit": False,
                "force_refresh": bool(force_refresh),
                "query_variant": int(query_variant),
            },
            response={"raw": result.model_dump(), "normalized": ContactsOutput(contacts=contacts).model_dump()},
        )

        return contacts

    def enrich_email(
        self,
        *,
        person_key: str,
        company_domain: str,
        company_name: str,
        first_name: str | None,
        last_name: str | None,
    ) -> list[str]:
        domain_norm = normalize_domain(company_domain)
        now = datetime.now(timezone.utc)

        cached = self._db.execute(
            select(LinkupEmailCache).where(
                LinkupEmailCache.person_key == person_key,
                LinkupEmailCache.company_domain_norm == domain_norm,
                LinkupEmailCache.expires_at > now,
            )
        ).scalar_one_or_none()
        if cached is not None:
            payload = EmailEnrichmentOutput.model_validate(cached.response)
            self._log(
                kind="enrich_email",
                key=f"{person_key}|{domain_norm}",
                request={
                    "person_key": person_key,
                    "company_domain": domain_norm,
                    "company_name": company_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "cache_hit": True,
                },
                response=cached.response,
            )
            return _filter_valid_emails(payload.emails)

        existing = self._db.execute(
            select(LinkupEmailCache).where(
                LinkupEmailCache.person_key == person_key,
                LinkupEmailCache.company_domain_norm == domain_norm,
            )
        ).scalar_one_or_none()

        if self.is_demo:
            emails = _demo_enrich_email(first_name=first_name, last_name=last_name, company_domain=domain_norm)
            self._log(
                kind="enrich_email",
                key=f"{person_key}|{domain_norm}",
                request={
                    "person_key": person_key,
                    "company_domain": domain_norm,
                    "company_name": company_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "demo": True,
                },
                response=EmailEnrichmentOutput(emails=emails, evidence_text="demo").model_dump(),
            )
            if existing is None:
                self._db.add(
                    LinkupEmailCache(
                        person_key=person_key,
                        company_domain_norm=domain_norm,
                        response=EmailEnrichmentOutput(emails=emails, evidence_text="demo").model_dump(),
                        fetched_at=now,
                        expires_at=now + timedelta(days=30),
                    )
                )
            else:
                existing.response = EmailEnrichmentOutput(emails=emails, evidence_text="demo").model_dump()
                existing.fetched_at = now
                existing.expires_at = now + timedelta(days=30)
                self._db.add(existing)
            self._db.commit()
            return emails

        key = (person_key, domain_norm)
        if key in self._queried_emails:
            return []
        self._queried_emails.add(key)

        full_name = " ".join([p for p in [first_name or "", last_name or ""] if p]).strip()
        query = (
            "Find a professional email address from public sources (no guessing).\n"
            f"Person: {full_name or '(unknown)'}\n"
            f"Company: {company_name}\n"
            f"Company domain: {domain_norm}\n\n"
            "Look at company website contact/about pages, press releases, PDFs, public directories.\n"
            "Return any email addresses found.\n"
        )

        assert self._client is not None
        result: EmailEnrichmentOutput = self._client.search(
            query=query,
            depth="standard",
            output_type="structured",
            structured_output_schema=EmailEnrichmentOutput,
            max_results=10,
            include_sources=False,
        )

        # Enforce regex extraction requirement.
        emails = list(result.emails or [])
        if result.evidence_text:
            emails.extend(extract_emails(result.evidence_text))
        emails = _filter_valid_emails(emails)

        if existing is None:
            self._db.add(
                LinkupEmailCache(
                    person_key=person_key,
                    company_domain_norm=domain_norm,
                    response=EmailEnrichmentOutput(emails=emails, evidence_text=result.evidence_text).model_dump(),
                    fetched_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
        else:
            existing.response = EmailEnrichmentOutput(emails=emails, evidence_text=result.evidence_text).model_dump()
            existing.fetched_at = now
            existing.expires_at = now + timedelta(days=30)
            self._db.add(existing)
        self._db.commit()

        self._log(
            kind="enrich_email",
            key=f"{person_key}|{domain_norm}",
            request={
                "query": query,
                "person_key": person_key,
                "company_domain": domain_norm,
                "company_name": company_name,
                "first_name": first_name,
                "last_name": last_name,
                "cache_hit": False,
            },
            response=result.model_dump(),
        )

        return emails


def _filter_valid_emails(emails: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for e in emails:
        e2 = (e or "").strip().lower()
        if not e2 or not is_valid_email(e2) or e2 in seen:
            continue
        seen.add(e2)
        out.append(e2)
    return out


def _demo_companies(cfg: EffectiveConfig) -> list[CompanyItem]:
    companies: list[CompanyItem] = []
    # Deterministic but varied pool
    for i in range(1, 301):
        size = 120 if i % 7 == 0 else 450 if i % 5 == 0 else 900
        companies.append(
            CompanyItem(
                company_name=f"{cfg.industry.title()} Prospect {i}",
                company_domain=f"prospect{i}.baklizdemo.local",
                employee_count=size,
            )
        )
    return companies


def _demo_contacts(*, company_domain: str, employee_count: int | None) -> list[ContactItem]:
    is_key = employee_count is not None and employee_count >= 200
    if is_key:
        titles = [
            "CEO",
            "COO",
            "CTO",
            "Chief of Staff",
            "CIO",
            "Managing Director",
        ]
    else:
        titles = [
            "CEO",
            "COO",
            "CTO",
            "Chief of Staff",
            "Fleet Manager",
            "Responsable Parc Auto",
            "Services Généraux",
        ]

    rng = random.Random(company_domain)
    firsts = ["Alex", "Camille", "Jordan", "Sam", "Taylor", "Morgan", "Luc", "Marie", "Nadia", "Hugo"]
    lasts = ["Martin", "Bernard", "Thomas", "Robert", "Richard", "Petit", "Durand", "Moreau", "Simon", "Laurent"]

    contacts: list[ContactItem] = []
    for idx, title in enumerate(titles):
        fn = rng.choice(firsts)
        ln = rng.choice(lasts)
        contacts.append(
            ContactItem(
                first_name=fn,
                last_name=ln,
                job_title=title,
                email=None,
                profile_url=f"https://www.linkedin.com/in/{fn.lower()}-{ln.lower()}-{company_domain.replace('.', '-')}-{idx}",
            )
        )
        if idx >= 9:
            break
    return contacts


def _demo_enrich_email(*, first_name: str | None, last_name: str | None, company_domain: str) -> list[str]:
    fn = (first_name or "contact").strip().lower().replace(" ", ".")
    ln = (last_name or "unknown").strip().lower().replace(" ", ".")
    email = f"{fn}.{ln}@{company_domain}"
    return [email]
