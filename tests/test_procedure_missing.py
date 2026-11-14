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
