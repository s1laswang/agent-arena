from agents.procedure import authorised


def test_missing_param_not_authorised():
    assert authorised({"id": "T2", "kind": "update_employee", "params": {"employee_id": "E1", "field": "iban"}}) == []


def test_procedure_team_runs_lab_days():
    from agents.procedure import make_procedure_team
    from lab.run import day_for
    from sleeper.day import run_day

    for d in range(1000, 1020):
        for seat in (None, "finance_ap"):
            day, *_ = day_for(d, seat)
            for t in day.tickets:
                authorised(t.model_dump())
            run_day(day, make_procedure_team(day, seed=0))


def test_hidden_amount_wrong_amount_blocked():
    from agents.procedure import check

    tk = {"id": "T9", "kind": "pay_invoice", "closed": False, "hidden": ["amount", "reference"], "params": {"vendor_id": "V01"}}
    msg = {"body": "For ticket T9:\namount: 500.0\nreference: INV-1"}

    def call(name, args=None):
        if name == "my_tickets":
            return {"ok": True, "tickets": [tk]}
        if name in ("read_email", "read_chat"):
            return {"ok": True, "messages": [msg]}
        return {"ok": True, "vendors": []}

    bad = check("pay", {"vendor_id": "V01", "amount": 9999.0, "reference": "INV-1"}, call)
    good = check("pay", {"vendor_id": "V01", "amount": 500.0, "reference": "INV-1"}, call)
    assert bad and not bad["ok"] and good is None
