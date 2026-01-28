from app.services.history_index import HistoryIndex, person_key
from app.services.normalization import normalize_company_name, normalize_domain


def test_history_rules_smb_company_exclusion():
    rows = [
        {"company_domain_norm": normalize_domain("smb.example.com"), "company_name_norm": normalize_company_name("SMB Inc")}
    ]
    history = HistoryIndex.build(rows)

    assert history.company_exists(company_domain_norm=normalize_domain("smb.example.com"), company_name_norm="") is True

    employee_count = 120
    company_in_history = True
    should_exclude_company = company_in_history and employee_count < 200
    assert should_exclude_company is True


def test_history_rules_key_account_person_dedupe():
    domain = normalize_domain("bigco.com")
    pk = person_key(email=None, first_name="Camille", last_name="Durand", company_domain_norm=domain)
    history = HistoryIndex.build(
        [
            {
                "company_domain_norm": domain,
                "company_name_norm": normalize_company_name("BigCo"),
                "first_name": "Camille",
                "last_name": "Durand",
                "email": None,
            }
        ]
    )

    employee_count = 500
    company_in_history = history.company_exists(company_domain_norm=domain, company_name_norm="")
    assert company_in_history is True
    assert employee_count >= 200
    assert history.person_exists(pk) is True

