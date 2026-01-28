from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


RunModeEnum = Enum("live", "dry_run", name="run_mode")
BlacklistEntryTypeEnum = Enum("company_name", "domain", name="blacklist_entry_type")


class Config(Base):
    __tablename__ = "config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(Text, default="", nullable=False)
    company_size_min: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    daily_objective: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    email_subject_template: Mapped[str] = mapped_column(Text, default="Hello {{Company}}", nullable=False)
    email_body_template: Mapped[str] = mapped_column(
        Text,
        default="Hi {{FirstName}},\n\nI wanted to reach out to {{Company}}.\n",
        nullable=False,
    )
    alert_email: Mapped[str] = mapped_column(Text, default="", nullable=False)
    run_mode: Mapped[str] = mapped_column(RunModeEnum, default="dry_run", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class BlacklistEntry(Base):
    __tablename__ = "blacklist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_type: Mapped[str] = mapped_column(BlacklistEntryTypeEnum, nullable=False)
    value_raw: Mapped[str] = mapped_column(Text, nullable=False)
    value_norm: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class History(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    company_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_title: Mapped[str | None] = mapped_column(Text, nullable=True)

    status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)

    company_domain_norm: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    company_name_norm: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    email_norm: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)


class RunLog(Base):
    __tablename__ = "run_logs"

    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    quota: Mapped[int] = mapped_column(Integer, nullable=False)
    created_drafts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enrich_failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pool_exhausted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    errors: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    run_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    overrides: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class LinkupCompanySearchCache(Base):
    __tablename__ = "linkup_company_search_cache"
    __table_args__ = (
        UniqueConstraint("industry", "location", "company_size_min", "query_date", name="uq_company_search_cache"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    company_size_min: Mapped[int] = mapped_column(Integer, nullable=False)
    query_date: Mapped[date] = mapped_column(Date, nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class LinkupContactsCache(Base):
    __tablename__ = "linkup_contacts_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_domain_norm: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class LinkupEmailCache(Base):
    __tablename__ = "linkup_email_cache"
    __table_args__ = (UniqueConstraint("person_key", "company_domain_norm", name="uq_email_cache_person_company"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_key: Mapped[str] = mapped_column(Text, nullable=False)
    company_domain_norm: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class ZeliqEnrichmentJob(Base):
    __tablename__ = "zeliq_enrichment_jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    person_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    company_domain_norm: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)

    request_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class ProviderLog(Base):
    __tablename__ = "provider_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)

    request: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
