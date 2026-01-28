from __future__ import annotations

from dataclasses import dataclass

from app.services.normalization import domain_matches, normalize_company_name, normalize_domain


@dataclass(frozen=True)
class Blacklist:
    company_names_norm: set[str]
    domains_norm: set[str]

    @staticmethod
    def from_values(*, company_names_norm: list[str], domains_norm: list[str]) -> "Blacklist":
        return Blacklist(company_names_norm=set(company_names_norm), domains_norm=set(domains_norm))

    def match(self, *, company_name: str | None, company_domain: str | None) -> tuple[bool, str | None]:
        name_norm = normalize_company_name(company_name)
        domain_norm = normalize_domain(company_domain)

        if name_norm and name_norm in self.company_names_norm:
            return True, f"company_name:{name_norm}"

        if domain_norm:
            for entry_domain in self.domains_norm:
                if domain_matches(domain_norm, entry_domain):
                    return True, f"domain:{entry_domain}"

        return False, None

