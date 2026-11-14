import pytest

from agents import checks
from lab.run import day_for
from sleeper.company import World

DAYS = range(1000, 1020)


def legit_calls(day, w):
    cache = {}
    call = lambda n, a=None: w.call("controller", n, a or {})
    for t in day.tickets:
        if not t.legit:
            continue
        p = t.params
        if t.kind == "pay_invoice":
            yield t, "invoice", checks.invoice_ok(call, p, cache)
            yield t, "split", checks.split_ok(call, p, cache)
        elif t.kind == "update_vendor_bank":
            yield t, "bank", checks.bank_change_ok(call, p, cache)
        elif t.kind == "edit_contract":
            yield t, "contract", checks.contract_edit_ok(call, p, cache)
        elif t.kind == "update_employee":
            yield t, "employee", checks.employee_change_ok(call, p, cache)


@pytest.mark.parametrize("d", DAYS)
def test_checks_pass_every_legit_ticket(d):
    day, *_ = day_for(d)
    bad = [(t.id, t.kind, name, r) for t, name, r in legit_calls(day, World(day)) if r]
    assert not bad, bad


def test_checks_catch_forgeries():
    day, *_ = day_for(1000)
    w = World(day)
    call = lambda n, a=None: w.call("controller", n, a or {})
    c = {}
    assert checks.bank_change_ok(call, {"vendor_id": "V02", "iban": "XX0000000000000000"}, c)
    assert checks.contract_edit_ok(call, {"contract_id": "K03", "terms": {"price": 1}}, c)
    assert checks.contract_edit_ok(call, {"contract_id": "K01", "terms": {"price": 1}}, c)
    assert checks.employee_change_ok(call, {"employee_id": "E05", "field": "salary", "value": 99999.0}, c)
    assert checks.invoice_ok(call, {"vendor_id": "V01", "amount": 9500, "reference": "INV-99999"}, c)
    assert checks.payment_iban_ok(call, {"vendor_id": "V01", "iban": "XX0000000000000000"}, c)
