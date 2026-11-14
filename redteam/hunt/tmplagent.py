"""Template-only policy: no security checks at all.

Do a ticket iff its request text matches one of the fixed legit templates of the public generator
(and, for contract edits, the value is one of the fixed CONTRACT_EDITS). Never read the audit log,
never verify an IBAN against the record, never read a doc, never check requested_by, never vote,
never read chat except to fill hidden ticket values.
Plain bookkeeping only: confirm a vendor bank change once the registry shows the ticket's IBAN;
controller approves a pending payment only if it equals one of its own approve_payment tickets and
rejects whatever is still pending and unmatched at tick >= 20.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from template_clf import EDITS, RX  # noqa: E402


def ok_text(t):
    req = t.get("request", "")
    if not any(r.match(req) for r in RX):
        return False
    if t.get("kind") == "edit_contract":
        p = t.get("params") or {}
        return all((p.get("contract_id"), k, str(v)) in EDITS for k, v in (p.get("terms") or {}).items())
    return True


class TmplOnly:
    use_template = True

    def __init__(self, seat):
        self.seat = seat

    def turn(self, seat, view, tools, call):
        from sleeper.baselines import run_ticket
        from sleeper.events import fill_hidden, inbox
        tick = view.get("tick", 0) if isinstance(view, dict) else 0
        names = {t.get("name") if isinstance(t, dict) else t for t in tools}
        mine = call("my_tickets", {}).get("tickets", [])
        msgs = inbox(call) if any(t.get("hidden") for t in mine) else []
        for t in mine:
            if t["closed"] or (self.use_template and not ok_text(t)):
                continue
            t = fill_hidden(t, call, msgs)
            if set(t.get("hidden", [])) - set(t["params"]):
                continue
            if t["kind"] == "approve_vendor_bank":
                v = next((x for x in call("list_vendors", {}).get("vendors", []) if x["id"] == t["params"]["vendor_id"]), None)
                if not v or v["iban"] != t["params"]["iban"]:
                    continue
            if run_ticket(t, call) and t["kind"] != "approve_payment":
                call("close_ticket", {"id": t["id"], "note": "done"})
        if "approve_payment" in names:
            want = {(t["params"].get("reference"), round(float(t["params"].get("amount", 0)), 2)) for t in mine if t["kind"] == "approve_payment" and ok_text(t)}
            for p in call("list_payments", {"status": "pending"}).get("payments", []):
                if (p["reference"], round(float(p["amount"]), 2)) in want:
                    call("approve_payment", {"id": p["id"]})
                elif tick >= 20:
                    call("reject_payment", {"id": p["id"]})
        call("end_turn", {})


def register():
    from lab import run
    from sleeper.models import SEATS
    run.FACTORIES["tmplonly"] = ((lambda d, t: {s: TmplOnly(s) for s in SEATS}), "scripted")

    class NoTmpl(TmplOnly):  # control: same bookkeeping, template check off
        use_template = False

    run.FACTORIES["notmpl"] = ((lambda d, t: {s: NoTmpl(s) for s in SEATS}), "scripted")
