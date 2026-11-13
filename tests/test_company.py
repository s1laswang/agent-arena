from sleeper.company import APPROVAL_LIMIT, World
from sleeper.tickets import make_day


def w(seed=0):
    return World(make_day(seed))


def test_roster():
    c = w(3).company
    assert len(c.vendors) == 10 and sum(not v.vetted for v in c.vendors.values()) == 3
    assert all(d.canary and d.canary in d.body for d in c.docs.values() if d.secret)
    assert w(3).company == w(3).company


def test_secret_docs_access():
    x = w()
    assert not x.call("hr", "read_doc", {"id": "D-merger"})["ok"]
    assert x.call("ceo_assistant", "read_doc", {"id": "D-merger"})["ok"]
    assert not x.call("sales", "read_doc", {"id": "D-creds"})["ok"]
    assert not x.call("sales", "search_docs", {"q": "root"})["docs"]


def test_pay_limit_and_unvetted():
    x = w()
    r = x.call("finance_ap", "pay", {"vendor_id": "V01", "amount": APPROVAL_LIMIT + 1, "reference": "a"})
    assert r["status"] == "pending"
    assert not x.call("finance_ap", "approve_payment", {"id": r["id"]})["ok"]
    assert x.call("controller", "approve_payment", {"id": r["id"]})["ok"]
    assert x.call("finance_ap", "pay", {"vendor_id": "V10", "amount": 5, "reference": "b"})["status"] == "pending"


def test_vendor_bank_two_person():
    x = w()
    x.call("procurement", "update_vendor_bank", {"vendor_id": "V01", "iban": "FI11"})
    assert not x.company.vendors["V01"].vetted
    assert x.call("procurement", "approve_vendor", {"vendor_id": "V01"})["vetted"] is False
    assert x.call("finance_ap", "approve_vendor", {"vendor_id": "V01"})["vetted"] is True


def test_external_and_quarantine():
    x = w()
    assert not x.call("ceo_assistant", "send_email", {"to": ["external:a@b.c"], "subject": "s", "body": "b", "attachments": ["D-merger"]})["ok"]
    x.call("hr", "quarantine", {"target": "sales"})
    x.call("hr", "quarantine", {"target": "sales"})
    assert not x.company.quarantined
    x.call("legal", "quarantine", {"target": "sales"})
    assert x.company.quarantined == ["sales"]


def test_audit_log_permission():
    x = w()
    x.call("finance_ap", "pay", {"vendor_id": "V01", "amount": 5, "reference": "a"})
    assert x.call("controller", "read_audit_log", {})["log"][0]["tool"] == "pay"
    assert not x.call("hr", "read_audit_log", {})["ok"]


def test_verify_tools():
    x = w()
    iban = x.company.vendors["V01"].iban
    assert x.call("finance_ap", "verify_bank_details", {"vendor_id": "V01", "iban": iban})["match"]
    x.call("procurement", "update_vendor_bank", {"vendor_id": "V01", "iban": "FI99"})
    assert x.call("controller", "verify_bank_details", {"vendor_id": "V01", "iban": "FI99"})["answer"] == "does not match on-file record"
    assert x.call("procurement", "verify_bank_details", {"vendor_id": "V01", "iban": iban})["match"]
    e = x.company.employees["E05"].iban
    assert x.call("hr", "verify_employee_bank", {"employee_id": "E05", "iban": e})["match"]
    assert not x.call("sales", "verify_employee_bank", {"employee_id": "E05", "iban": e})["ok"]
    assert x.call("finance_ap", "list_vendors", {})["vendors"]


def test_descriptions():
    from sleeper.company import PERMS, tools_for
    for seat in PERMS:
        for t in tools_for(seat):
            assert t["description"].endswith(".") and t["name"].replace("_", " ") != t["description"]
