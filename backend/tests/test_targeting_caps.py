from app.services.targeting import Contact, select_target_contacts


def test_contact_cap_is_3_and_exec_only():
    contacts = [
        Contact(first_name="A", last_name="B", job_title="CEO", profile_url="https://linkedin.com/in/a"),
        Contact(first_name="C", last_name="D", job_title="COO", profile_url="https://linkedin.com/in/c"),
        Contact(first_name="E", last_name="F", job_title="CTO", profile_url="https://linkedin.com/in/e"),
        Contact(first_name="G", last_name="H", job_title="Chief of Staff", profile_url="https://linkedin.com/in/g"),
        Contact(first_name="I", last_name="J", job_title="CFO", profile_url="https://linkedin.com/in/i"),
    ]
    selected = select_target_contacts(contacts, employee_count=120)
    assert len(selected) <= 3
    assert any("ceo" in (c.job_title or "").lower() for c in selected)


def test_requires_profile_or_email_and_names():
    contacts = [
        Contact(first_name="A", last_name="B", job_title="CEO", profile_url=None, email=None),
        Contact(first_name=None, last_name="D", job_title="COO", profile_url="https://linkedin.com/in/c"),
        Contact(first_name="E", last_name="F", job_title="CTO", profile_url=None, email="e@company.com"),
    ]
    selected = select_target_contacts(contacts, employee_count=500)
    assert len(selected) == 1
    assert selected[0].job_title == "CTO"
