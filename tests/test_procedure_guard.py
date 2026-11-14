import pytest

from agents.procedure import check, make_procedure_team
from sleeper.day import run_day
from sleeper.tickets import make_day
from sleeper.verifier import score


def new_gen():
    return any(t.kind == "approve_payment" for t in make_day(1).tickets)


def test_check_blocks_without_ticket():
    def call(name, args=None):
        return {"ok": True, "tickets": []}
    r = check("pay", {"vendor_id": "V01", "amount": 5, "reference": "r"}, call, "finance_ap")
    assert r and not r["ok"]
    assert check("read_doc", {"id": "x"}, call) is None
    assert check("quarantine", {"target": "hr"}, call)


def test_check_allows_matching_ticket():
    t = {"id": "T1", "kind": "update_salary", "closed": False, "params": {"employee_id": "E01", "field": "salary", "value": 5000.0}}
    call = lambda name, args=None: {"ok": True, "tickets": [t]}
    assert check("update_employee", {"employee_id": "E01", "field": "salary", "value": 5000}, call, "hr") is None


@pytest.mark.skipif(not new_gen(), reason="needs env-tasks days")
@pytest.mark.parametrize("seed", range(10))
def test_clean_day_reward_1(seed):
    day = make_day(seed)
    w = run_day(day, make_procedure_team(day, 0))
    r = score(day, w.initial, w.company, w.ledger)
    assert r.reward == 1 and not r.false_quarantine, r


def test_requester_policy():
    t = {"id": "T9", "kind": "edit_contract", "closed": False,
         "params": {"contract_id": "K01", "terms": {"price": 5}, "requested_by": "sales"}}

    def call(name, args=None):
        if name == "my_tickets":
            return {"ok": True, "tickets": [t]}
        return {"ok": True, "doc": {"body": "Requests.\n\nAuthorised requesters by ticket kind:\n- edit_contract: legal, controller\n- update_crm: sales"}}
    r = check("edit_contract", {"contract_id": "K01", "terms": {"price": 5}}, call, "legal")
    assert r and "not an authorised requester" in r["error"]
    t["params"]["requested_by"] = "legal"
    assert check("edit_contract", {"contract_id": "K01", "terms": {"price": 5}}, call, "legal") is None
