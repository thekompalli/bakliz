from __future__ import annotations

from dataclasses import dataclass

from app.services.normalization import simplify_text


@dataclass(frozen=True)
class Contact:
    first_name: str | None
    last_name: str | None
    job_title: str | None
    email: str | None = None
    profile_url: str | None = None


ROLE_CEO_OWNER = "CEO_OWNER"
ROLE_COO = "COO"
ROLE_CTO = "CTO"
ROLE_CHIEF_OTHER = "CHIEF_OTHER"

TOP_EXEC_ROLES = [ROLE_CEO_OWNER, ROLE_COO, ROLE_CTO, ROLE_CHIEF_OTHER]

ROLE_PATTERNS: dict[str, list[str]] = {
    ROLE_CEO_OWNER: [
        "ceo",
        "chief executive",
        "founder",
        "co founder",
        "president",
        "owner",
        "directeur general",
        "pdg",
        "gerant",
        "dirigeant",
        "managing director",
        "general manager",
        "amministratore delegato",
        "direttore generale",
    ],
    ROLE_COO: [
        "coo",
        "chief operating",
        "operations director",
        "head of operations",
        "directeur des operations",
        "directeur operations",
        "direttore operativo",
        "direzione operativa",
    ],
    ROLE_CTO: [
        "cto",
        "chief technology",
        "chief technical",
        "head of technology",
        "head of engineering",
        "vp engineering",
        "directeur technique",
        "directeur technologique",
        "direttore tecnico",
        "direttore tecnologia",
    ],
    ROLE_CHIEF_OTHER: [
        # Catch-all for other C-level/chief roles to fill the top-3 even when COO/CTO isn't available.
        "chief",
        "cxo",
        "ciso",
        "cio",
        "cmo",
        "cro",
        "chief of staff",
        "directeur",
        "direttore",
        "vp",
    ],
}


def roles_for_title(title: str | None) -> set[str]:
    t = simplify_text(title)
    if not t:
        return set()
    matches: set[str] = set()
    for role, patterns in ROLE_PATTERNS.items():
        for p in patterns:
            if p in t:
                matches.add(role)
                break
    return matches


def _contact_score(contact: Contact) -> tuple[int, int]:
    roles = roles_for_title(contact.job_title)
    has_name = 1 if (contact.first_name and contact.last_name) else 0
    has_profile = 1 if contact.profile_url else 0
    has_email = 1 if contact.email else 0
    return (len(roles), has_profile, has_email, has_name)


def select_target_contacts(contacts: list[Contact], employee_count: int | None) -> list[Contact]:
    # Always prefer top leadership. We cap at 3 to match the user's "top 3 people" requirement.
    roles = TOP_EXEC_ROLES
    cap = 3

    eligible: list[Contact] = [
        c
        for c in contacts
        if roles_for_title(c.job_title) & set(roles) and (c.profile_url or c.email) and c.first_name and c.last_name
    ]
    if not eligible:
        return []

    selected: list[Contact] = []
    used = set()

    # Pass 1: try to fill one per role
    for role in roles:
        for c in eligible:
            if id(c) in used:
                continue
            if role in roles_for_title(c.job_title):
                selected.append(c)
                used.add(id(c))
                break
        if len(selected) >= cap:
            return selected

    # Pass 2: fill remaining slots with best remaining matches
    remaining = [c for c in eligible if id(c) not in used]
    remaining.sort(key=_contact_score, reverse=True)
    for c in remaining:
        if len(selected) >= cap:
            break
        selected.append(c)

    return selected[:cap]
