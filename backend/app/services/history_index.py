from __future__ import annotations

from dataclasses import dataclass

from app.services.normalization import normalize_company_name, normalize_domain, normalize_person_name


def email_person_key(email: str | None) -> str:
    if email and email.strip():
        return f"email:{email.strip().lower()}"
    return ""


def name_person_key(*, first_name: str | None, last_name: str | None, company_domain_norm: str | None) -> str:
    fn = normalize_person_name(first_name)
    ln = normalize_person_name(last_name)
    dom = (company_domain_norm or "").strip().lower()
    if fn and ln and dom:
        return f"name:{fn}|{ln}|{dom}"
    return ""


def person_key(
    *,
    email: str | None,
    first_name: str | None,
    last_name: str | None,
    company_domain_norm: str | None,
) -> str:
    return email_person_key(email) or name_person_key(first_name=first_name, last_name=last_name, company_domain_norm=company_domain_norm)


@dataclass
class HistoryIndex:
    company_domains: set[str]
    company_names: set[str]
    person_keys: set[str]

    @staticmethod
    def build(rows: list[dict]) -> "HistoryIndex":
        domains: set[str] = set()
        names: set[str] = set()
        people: set[str] = set()

        for r in rows:
            d = r.get("company_domain_norm") or normalize_domain(r.get("company_domain"))
            n = r.get("company_name_norm") or normalize_company_name(r.get("company_name"))
            if d:
                domains.add(d)
            if n:
                names.add(n)

            pk = person_key(
                email=r.get("email_norm") or r.get("email"),
                first_name=r.get("first_name"),
                last_name=r.get("last_name"),
                company_domain_norm=d,
            )
            if pk:
                people.add(pk)

            # Also store name-based key even if email exists, to satisfy the matching rule:
            # if candidate has no email, dedupe on (first + last + company_domain).
            npk = name_person_key(first_name=r.get("first_name"), last_name=r.get("last_name"), company_domain_norm=d)
            if npk:
                people.add(npk)

        return HistoryIndex(company_domains=domains, company_names=names, person_keys=people)

    def company_exists(self, *, company_domain_norm: str, company_name_norm: str) -> bool:
        if company_domain_norm and company_domain_norm in self.company_domains:
            return True
        if company_name_norm and company_name_norm in self.company_names:
            return True
        return False

    def person_exists(self, pk: str) -> bool:
        return pk in self.person_keys

    def add_person(self, pk: str) -> None:
        if pk:
            self.person_keys.add(pk)
