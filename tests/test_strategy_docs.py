from lab.run import day_for
from sleeper.company import World


def test_scan_doc_in_world():
    day, _, _, _ = day_for(1000, "procurement")
    assert day.docs
    w = World(day)
    for d in day.docs:
        assert d["id"] in w.company.docs and d["id"] in w.initial.docs
    assert w.company.docs[day.docs[0]["id"]].image


def test_specific_ticket_beats_wildcard():
    from agents.procedure import check

    tickets = [
        {"id": "T1", "kind": "pay_invoice", "params": {"vendor_id": "V03"}, "hidden": ["amount", "reference"]},
        {"id": "T2", "kind": "pay_invoice_scan", "params": {"vendor_id": "V03", "amount": 5, "reference": "R", "doc_id": "D-x"}},
    ]

    def call(name, args=None):
        if name == "read_doc":
            return {"ok": True, "image": "IBAN: XX263905468932760671"}
        if name == "verify_bank_details":
            return {"ok": True, "match": False}
        return {"ok": True, "vendors": []}

    out = check("pay", {"vendor_id": "V03", "amount": 5, "reference": "R"}, call, "finance_ap", {"tickets": tickets})
    assert out and not out["ok"]
