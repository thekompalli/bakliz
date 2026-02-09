"""seed blacklist from yooliz martin V2.xlsx

Revision ID: 007_seed_blklist_v2
Revises: 006_add_linkup_search_depth
Create Date: 2026-02-09
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import sqlalchemy as sa
from alembic import op

from app.services.normalization import extract_emails, normalize_company_name, normalize_domain


# revision identifiers, used by Alembic.
revision = "007_seed_blklist_v2"
down_revision = "006_add_linkup_search_depth"
branch_labels = None
depends_on = None


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


def _xlsx_path() -> Path:
    # /app/migrations/versions/<this_file.py> -> /app
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "Blacklist_excel" / "yooliz martin V2.xlsx"


def _insert_if_missing(entry_type: str, value_raw: str, value_norm: str) -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO blacklist_entries (entry_type, value_raw, value_norm)
            SELECT CAST(:entry_type AS blacklist_entry_type), :value_raw, :value_norm
            WHERE NOT EXISTS (
              SELECT 1 FROM blacklist_entries
              WHERE entry_type = CAST(:entry_type AS blacklist_entry_type) AND value_norm = :value_norm
            )
            """
        ).bindparams(entry_type=entry_type, value_raw=value_raw, value_norm=value_norm)
    )


def _delete_by_norm(entry_type: str, value_norm: str) -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM blacklist_entries
            WHERE entry_type = :entry_type AND value_norm = :value_norm
            """
        ).bindparams(entry_type=entry_type, value_norm=value_norm)
    )


def _xlsx_col_to_idx(col: str) -> int:
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _xlsx_text_of_si(si: ET.Element, ns: dict[str, str]) -> str:
    parts: list[str] = []
    for t in si.findall(".//main:t", ns):
        parts.append(t.text or "")
    return "".join(parts)


def _xlsx_cell_value(c: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str | None:
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
        if t_el is None:
            return None
        return t_el.text or ""

    v_el = c.find("main:v", ns)
    return None if v_el is None else v_el.text


def _xlsx_sheet_paths(z: zipfile.ZipFile) -> list[str]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    pkg_rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"

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

    paths: list[str] = []
    for _name, rid in wb_sheets:
        target = rels.get(rid)
        if not target:
            continue
        paths.append("xl/" + target.lstrip("/"))
    return paths


def _xlsx_shared_strings(z: zipfile.ZipFile) -> list[str]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    }
    if "xl/sharedStrings.xml" not in z.namelist():
        return []

    ss_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    shared: list[str] = []
    for si in ss_root.findall("main:si", ns):
        shared.append(_xlsx_text_of_si(si, ns))
    return shared


def _extract_blacklist_from_xlsx(xlsx_path: Path) -> tuple[dict[str, str], set[str]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    }

    companies_by_norm: dict[str, str] = {}
    domains_norm: set[str] = set()

    with zipfile.ZipFile(xlsx_path) as z:
        shared_strings = _xlsx_shared_strings(z)
        sheet_paths = [p for p in _xlsx_sheet_paths(z) if p in z.namelist()]

        for sheet_path in sheet_paths:
            root = ET.fromstring(z.read(sheet_path))

            rows = root.findall(".//main:sheetData/main:row", ns)
            if not rows:
                continue

            # Expect header on first row.
            header_cells: dict[int, str] = {}
            for c in rows[0].findall("main:c", ns):
                ref = c.get("r") or ""
                m = re.match(r"([A-Z]+)([0-9]+)$", ref)
                if not m:
                    continue
                idx = _xlsx_col_to_idx(m.group(1))
                v = _xlsx_cell_value(c, shared_strings, ns)
                if v is None:
                    continue
                header_cells[idx] = str(v).strip()

            if not header_cells:
                continue

            def header_idx(label: str) -> int | None:
                wanted = label.casefold()
                for i, v in header_cells.items():
                    if v.casefold() == wanted:
                        return i
                return None

            company_idx = header_idx("Entreprise")
            email_idx = header_idx("Email")
            if company_idx is None and email_idx is None:
                continue

            # Iterate remaining rows.
            for row in rows[1:]:
                row_cells: dict[int, str] = {}
                for c in row.findall("main:c", ns):
                    ref = c.get("r") or ""
                    m = re.match(r"([A-Z]+)([0-9]+)$", ref)
                    if not m:
                        continue
                    idx = _xlsx_col_to_idx(m.group(1))
                    v = _xlsx_cell_value(c, shared_strings, ns)
                    if v is None:
                        continue
                    row_cells[idx] = str(v).strip()

                if not row_cells:
                    continue

                if company_idx is not None:
                    raw_company = row_cells.get(company_idx, "").strip()
                    if raw_company:
                        norm = normalize_company_name(raw_company)
                        if norm and norm not in companies_by_norm:
                            companies_by_norm[norm] = raw_company

                if email_idx is not None:
                    email_cell = row_cells.get(email_idx, "")
                    if email_cell:
                        for email in extract_emails(email_cell):
                            dom = normalize_domain(email)
                            if not dom:
                                continue
                            if dom in PERSONAL_EMAIL_DOMAINS:
                                continue
                            domains_norm.add(dom)

    return companies_by_norm, domains_norm


def upgrade() -> None:
    xlsx_path = _xlsx_path()
    if not xlsx_path.exists():
        return

    companies_by_norm, domains_norm = _extract_blacklist_from_xlsx(xlsx_path)

    for norm, raw in sorted(companies_by_norm.items()):
        _insert_if_missing("company_name", raw, norm)

    for dom in sorted(domains_norm):
        _insert_if_missing("domain", dom, dom)


def downgrade() -> None:
    xlsx_path = _xlsx_path()
    if not xlsx_path.exists():
        return

    companies_by_norm, domains_norm = _extract_blacklist_from_xlsx(xlsx_path)

    for norm in sorted(companies_by_norm):
        _delete_by_norm("company_name", norm)

    for dom in sorted(domains_norm):
        _delete_by_norm("domain", dom)

