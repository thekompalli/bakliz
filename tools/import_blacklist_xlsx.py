#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
DOMAIN_CHARS_RE = re.compile(r"(?i)^[a-z0-9.-]+$")

# Guardrail: never blacklist personal email providers even if present in the sheet.
PERSONAL_EMAIL_DOMAINS = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "yahoo.com",
    "icloud.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "pm.me",
    "gmx.com",
    "gmx.fr",
    "orange.fr",
    "free.fr",
    "wanadoo.fr",
    "laposte.net",
}


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


def is_probable_domain(value: str) -> bool:
    if not value:
        return False
    if " " in value:
        return False
    if "." not in value:
        return False
    if value.startswith(".") or value.endswith("."):
        return False
    if not DOMAIN_CHARS_RE.fullmatch(value):
        return False
    return True


def parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
            val = val[1:-1]
        env[key] = val
    return env


def http_json(
    *,
    method: str,
    url: str,
    token: str | None = None,
    body: dict | None = None,
    timeout_seconds: int = 30,
) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, method=method, data=data)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urlopen(req, timeout=timeout_seconds) as res:
            raw = res.read()
            text = raw.decode("utf-8", errors="replace").strip()
            return {} if not text else json.loads(text)
    except HTTPError as e:
        raw = e.read()
        text = raw.decode("utf-8", errors="replace").strip()
        try:
            payload = {} if not text else json.loads(text)
        except json.JSONDecodeError:
            payload = {"detail": text or str(e)}
        payload["_http_status"] = e.code
        raise RuntimeError(payload.get("detail") or f"HTTP {e.code}") from None
    except URLError as e:
        raise RuntimeError(f"Network error: {e}") from None


@dataclass(frozen=True)
class SheetRef:
    name: str
    path: str


def _xlsx_text_of_si(si: ET.Element, ns: dict[str, str]) -> str:
    parts: list[str] = []
    for t in si.findall(".//main:t", ns):
        parts.append(t.text or "")
    return "".join(parts)


def _xlsx_col_to_idx(col: str) -> int:
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _xlsx_get_cell_value(c: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str | None:
    t = c.get("t")
    if t == "s":
        v_el = c.find("main:v", ns)
        if v_el is None or v_el.text is None:
            return None
        try:
            i = int(v_el.text)
        except ValueError:
            return None
        return shared_strings[i] if 0 <= i < len(shared_strings) else None

    if t == "inlineStr":
        t_el = c.find(".//main:t", ns)
        return None if t_el is None else (t_el.text or "")

    v_el = c.find("main:v", ns)
    return None if v_el is None else v_el.text


def _xlsx_iter_rows(sheet_xml: bytes, shared_strings: list[str], width: int) -> Iterable[list[str]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    }
    root = ET.fromstring(sheet_xml)
    for row in root.findall(".//main:sheetData/main:row", ns):
        cells: dict[int, str] = {}
        for c in row.findall("main:c", ns):
            ref = c.get("r") or ""
            m = re.match(r"([A-Z]+)([0-9]+)$", ref)
            if not m:
                continue
            col = m.group(1)
            idx = _xlsx_col_to_idx(col)
            v = _xlsx_get_cell_value(c, shared_strings, ns)
            if v is None:
                continue
            cells[idx] = str(v).strip()

        if not cells:
            continue

        # Sheet XML is sparse: a missing cell means empty value.
        row_values = [cells.get(i, "") for i in range(width)]
        yield row_values


def read_xlsx_sheets(path: Path) -> tuple[list[SheetRef], list[str]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    pkg_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"

    with zipfile.ZipFile(path) as z:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("main:si", ns):
                shared_strings.append(_xlsx_text_of_si(si, ns))

        wb_root = ET.fromstring(z.read("xl/workbook.xml"))
        wb_sheets: list[tuple[str, str]] = []
        for sh in wb_root.findall("main:sheets/main:sheet", ns):
            wb_sheets.append((sh.get("name") or "", sh.get(f"{{{ns['rel']}}}id") or ""))

        rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rels: dict[str, str] = {}
        for rel in rels_root.findall(f"{{{pkg_rel_ns}}}Relationship"):
            rid = rel.get("Id") or ""
            target = rel.get("Target") or ""
            if rid and target:
                rels[rid] = target

        sheets: list[SheetRef] = []
        for name, rid in wb_sheets:
            target = rels.get(rid)
            if not target:
                continue
            sheet_path = "xl/" + target.lstrip("/")
            sheets.append(SheetRef(name=name, path=sheet_path))
        return sheets, shared_strings


def extract_blacklist_values_from_xlsx(path: Path) -> tuple[dict[str, str], set[str]]:
    """
    Returns:
      - companies_by_norm: map norm -> best raw label (Entreprise column)
      - domains_norm: normalized domains extracted from Email column
    """
    sheets, shared_strings = read_xlsx_sheets(path)
    companies_by_norm: dict[str, str] = {}
    domains_norm: set[str] = set()

    with zipfile.ZipFile(path) as z:
        for sheet in sheets:
            if sheet.path not in z.namelist():
                continue

            # First pass: read header row to get width and column indices.
            # We assume the first non-empty row is the header.
            it = iter(_xlsx_iter_rows(z.read(sheet.path), shared_strings, width=256))
            header = None
            for row_values in it:
                if any(v.strip() for v in row_values):
                    header = [v.strip() for v in row_values]
                    break
            if not header:
                continue

            header_trimmed = [h for h in header if h != ""]
            width = max(1, len(header_trimmed))
            header_keys = [h.strip().casefold() for h in header[:width]]

            def idx_of(col_name: str) -> int | None:
                try:
                    return header_keys.index(col_name.casefold())
                except ValueError:
                    return None

            company_idx = idx_of("Entreprise")
            email_idx = idx_of("Email")
            if company_idx is None and email_idx is None:
                continue

            # Second pass: iterate again with the real width.
            for row_values in _xlsx_iter_rows(z.read(sheet.path), shared_strings, width=width):
                if row_values == header[:width]:
                    continue

                if company_idx is not None and company_idx < len(row_values):
                    raw_company = row_values[company_idx].strip()
                    if raw_company:
                        norm = normalize_company_name(raw_company)
                        if norm and norm not in companies_by_norm:
                            companies_by_norm[norm] = raw_company

                if email_idx is not None and email_idx < len(row_values):
                    email_cell = row_values[email_idx].strip()
                    if not email_cell:
                        continue
                    emails = EMAIL_RE.findall(email_cell)
                    for email in emails:
                        dom = normalize_domain(email)
                        if not dom or not is_probable_domain(dom):
                            continue
                        if dom in PERSONAL_EMAIL_DOMAINS:
                            continue
                        domains_norm.add(dom)

    return companies_by_norm, domains_norm


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Import blacklist entries from an .xlsx file (Entreprise + Email columns).")
    ap.add_argument(
        "xlsx",
        nargs="?",
        default="bakliz/Blacklist_excel/yooliz martin V2.xlsx",
        help="Path to the .xlsx file (default: %(default)s)",
    )
    ap.add_argument("--api-base", default="http://localhost:8000", help="Backend API base URL (default: %(default)s)")
    ap.add_argument(
        "--env-file",
        default=None,
        help="Env file providing ADMIN_USERNAME/ADMIN_PASSWORD (default: bakliz/infra/.env then bakliz/.env)",
    )
    ap.add_argument("--include-domains", action="store_true", help="Also blacklist email domains extracted from the sheet")
    ap.add_argument("--apply", action="store_true", help="Apply changes (otherwise dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="Only insert first N entries (debug)")
    args = ap.parse_args(argv)

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        print(f"ERROR: file not found: {xlsx_path}", file=sys.stderr)
        return 2

    companies_by_norm, domains_norm = extract_blacklist_values_from_xlsx(xlsx_path)
    companies = [companies_by_norm[n] for n in sorted(companies_by_norm)]
    domains = sorted(domains_norm) if args.include_domains else []

    print(f"Extracted from {xlsx_path}:")
    print(f"- Companies: {len(companies)} unique (from Entreprise column)")
    if args.include_domains:
        print(f"- Domains:   {len(domains)} unique (from Email column)")
    else:
        print("- Domains:   (skipped; pass --include-domains to enable)")

    if not args.apply:
        if companies:
            print(f"Sample company: {companies[0]!r}")
        if domains:
            print(f"Sample domain:  {domains[0]!r}")
        print("Dry-run: no changes applied. Re-run with --apply to insert entries via the API.")
        return 0

    # Read credentials
    if args.env_file:
        env_path = Path(args.env_file)
    else:
        env_path = Path("bakliz/infra/.env") if Path("bakliz/infra/.env").exists() else Path("bakliz/.env")
    env = parse_dotenv(env_path)
    username = env.get("ADMIN_USERNAME") or "admin"
    password = env.get("ADMIN_PASSWORD") or ""
    if not password:
        print(f"ERROR: ADMIN_PASSWORD is empty in {env_path}", file=sys.stderr)
        return 2

    api_base = args.api_base.rstrip("/")

    # Login
    login = http_json(
        method="POST",
        url=f"{api_base}/api/auth/login",
        body={"username": username, "password": password},
    )
    token = str(login.get("access_token") or "")
    if not token:
        print("ERROR: login failed (no access_token returned)", file=sys.stderr)
        return 2

    # Fetch existing norms to keep imports idempotent.
    existing_company: set[str] = set()
    existing_domain: set[str] = set()
    page = 1
    page_size = 200
    while True:
        resp = http_json(
            method="GET",
            url=f"{api_base}/api/blacklist?page={page}&page_size={page_size}",
            token=token,
        )
        items = resp.get("items") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            t = str(it.get("entry_type") or "")
            n = str(it.get("value_norm") or "")
            if not t or not n:
                continue
            if t == "company_name":
                existing_company.add(n)
            elif t == "domain":
                existing_domain.add(n)

        total = int(resp.get("total") or 0)
        if page * page_size >= total:
            break
        page += 1

    to_insert: list[tuple[str, str]] = []
    for raw in companies:
        norm = normalize_company_name(raw)
        if norm and norm not in existing_company:
            to_insert.append(("company_name", raw))
    for dom in domains:
        norm = normalize_domain(dom)
        if norm and norm not in existing_domain:
            to_insert.append(("domain", dom))

    if args.limit and args.limit > 0:
        to_insert = to_insert[: args.limit]

    print(f"Will insert: {len(to_insert)} new entries (skipping existing).")

    inserted = 0
    failed = 0
    for i, (entry_type, value) in enumerate(to_insert, start=1):
        try:
            http_json(
                method="POST",
                url=f"{api_base}/api/blacklist",
                token=token,
                body={"entry_type": entry_type, "value": value},
            )
            inserted += 1
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(to_insert)}] FAILED {entry_type} {value!r}: {e}", file=sys.stderr)
            continue

        if i % 25 == 0 or i == len(to_insert):
            print(f"[{i}/{len(to_insert)}] inserted={inserted} failed={failed}")

    print(f"Done. inserted={inserted} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

