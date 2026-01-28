from __future__ import annotations


def render_template(template: str, *, first_name: str | None, company: str | None) -> str:
    first = (first_name or "").strip() or "there"
    comp = (company or "").strip() or "your company"
    return (
        template.replace("{{FirstName}}", first)
        .replace("{{Company}}", comp)
        .replace("{{FIRSTNAME}}", first)
        .replace("{{COMPANY}}", comp)
    )

