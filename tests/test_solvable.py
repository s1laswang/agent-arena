import re

from sleeper.company import PERMS, World
from sleeper.daymix import day_spec, entry
from sleeper.models import SEATS
from sleeper.tickets import TOOL_FOR_KIND, make_day

SEEDS = range(40)
IDS = re.compile(r"\b(DOC-[A-Za-z0-9-]+|D-[A-Za-z0-9-]+|V\d{2}|E\d{2}|acc_[a-z_0-9]+)\b")


def readable(w, seat, doc_id):
    return w.call(seat, "read_doc", {"id": doc_id}).get("ok", False)


def world(seed):
    day = make_day(seed)
    return day, World(day)


def test_every_legit_ticket_has_its_tool():
    for s in SEEDS:
        day, _ = world(s)
        for t in day.tickets:
            tool = TOOL_FOR_KIND[t.kind]
            assert tool in PERMS[t.seat], (s, t.id, t.seat, tool)


def test_every_named_id_exists_and_is_readable():
    for s in SEEDS:
        day, w = world(s)
        c = w.company
        for t in day.tickets:
            for i in IDS.findall(t.request):
                if i.startswith(("DOC-", "D-")):
                    assert i in c.docs, (s, t.id, i)
                    assert readable(w, t.seat, i), (s, t.id, i, t.seat)
                elif i.startswith("V"):
                    assert i in c.vendors, (s, t.id, i)
                elif i.startswith("E"):
                    assert i in c.employees, (s, t.id, i)
                else:
                    assert i in c.accounts, (s, t.id, i)


def test_every_malicious_ticket_has_readable_contradicting_evidence():
    for s in SEEDS:
        e = entry(s)
        if e["sleeper_seat"] is None:
            continue
        spec = day_spec(s)
        strat = spec["strategy"]
        assert strat.tells and strat.counter, (s, strat.id)
        for t in spec["tickets"]:
            assert not t.legit
            w = World(make_day(s))
            assert readable(w, t.seat, "D-policy"), (s, t.id)
            for iban in re.findall(r"FI\d{16}", t.request + str(t.params)):
                assert {"list_vendors", "verify_bank_details", "read_audit_log"} & PERMS[t.seat], (s, t.id, t.seat)
