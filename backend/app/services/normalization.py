from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_company_name(name: str | None) -> str:
    if not name:
        return ""
    text = strip_accents(name).lower().strip()
    text = re.sub(r"[^a-z0-9\s&'()-]", " ", text)
    return collapse_ws(text)


def normalize_person_name(name: str | None) -> str:
    if not name:
        return ""
    text = strip_accents(name).lower().strip()
    text = re.sub(r"[^a-z0-9\s'-]", " ", text)
    return collapse_ws(text)


def normalize_domain(value: str | None) -> str:
    if not value:
        return ""

    raw = value.strip().lower()

    # If an email was provided, keep domain part.
    if "@" in raw and " " not in raw and "/" not in raw:
        raw = raw.split("@")[-1]

    to_parse = raw
    if "://" not in to_parse:
        to_parse = "http://" + to_parse

    parsed = urlparse(to_parse)
    host = parsed.netloc or parsed.path
    host = host.split("/")[0].split(":")[0].strip().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_matches(candidate_domain: str | None, blacklist_domain: str) -> bool:
    candidate = normalize_domain(candidate_domain)
    entry = normalize_domain(blacklist_domain)
    if not candidate or not entry:
        return False
    return candidate == entry or candidate.endswith("." + entry)


def is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    return bool(EMAIL_RE.fullmatch(email.strip()))


def extract_emails(text: str) -> list[str]:
    emails = EMAIL_RE.findall(text or "")
    deduped: list[str] = []
    seen: set[str] = set()
    for e in emails:
        e2 = e.strip().lower()
        if e2 not in seen:
            seen.add(e2)
            deduped.append(e2)
    return deduped


def simplify_text(text: str | None) -> str:
    if not text:
        return ""
    t = strip_accents(text).lower()
    t = re.sub(r"[^a-z0-9\s/+&-]", " ", t)
    return collapse_ws(t)

