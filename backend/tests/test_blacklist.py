from app.services.blacklist import Blacklist
from app.services.normalization import normalize_company_name, normalize_domain


def test_blacklist_company_name_case_insensitive():
    bl = Blacklist.from_values(company_names_norm=[normalize_company_name("Acme Corporation")], domains_norm=[])
    matched, _ = bl.match(company_name="ACME corporation", company_domain="acme.test")
    assert matched is True


def test_blacklist_domain_matches_subdomains():
    bl = Blacklist.from_values(company_names_norm=[], domains_norm=[normalize_domain("example.com")])
    assert bl.match(company_name="X", company_domain="example.com")[0] is True
    assert bl.match(company_name="X", company_domain="mail.example.com")[0] is True
    assert bl.match(company_name="X", company_domain="www.example.com")[0] is True
    assert bl.match(company_name="X", company_domain="other.com")[0] is False

