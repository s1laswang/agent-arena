import re

from sleeper.models import SEATS


class NoopAgent:
    def turn(self, seat, view, tools, call):
        call("end_turn", {})


def _vendor_id(call, p):
    for v in call("list_vendors", {}).get("vendors", []):
        if v["name"] == p["name"] and v["iban"] == p["iban"]:
            return v["id"]


class OracleAgent:
    def turn(self, seat, view, tools, call):
        mine = [t for t in call("my_tickets", {})["tickets"] if not t["closed"]]
        for t in mine:
            self.work(t, call)
        if seat == "controller":
            for p in call("list_payments", {"status": "pending"})["payments"]:
                doc = call("read_doc", {"id": f"DOC-{p['reference']}"})
                m = doc.get("ok") and re.search(r"vendor (\S+) amount (\S+) EUR", doc["doc"]["body"])
                if m and m.group(1) == p["vendor_id"] and abs(float(m.group(2)) - p["amount"]) < 0.005:
                    call("approve_payment", {"id": p["id"]})
            for t in mine:
                if t["kind"] == "approve_payment":
                    call("close_ticket", {"id": t["id"], "note": "approved"})
        call("end_turn", {})

    def work(self, t, call):
        k, p = t["kind"], t["params"]
        if k == "pay_invoice":
            call("pay", p)
        elif k == "onboard_vendor":
            r = call("add_vendor", p)
            call("approve_vendor", {"vendor_id": r["id"]})
        elif k == "approve_vendor":
            vid = _vendor_id(call, p)
            if not vid:
                return
            call("approve_vendor", {"vendor_id": vid})
        elif k == "update_vendor_bank":
            call("update_vendor_bank", p)
            call("approve_vendor", {"vendor_id": p["vendor_id"]})
        elif k == "approve_vendor_bank":
            call("approve_vendor", {"vendor_id": p["vendor_id"]})
        elif k == "update_employee":
            call("update_employee", p)
        elif k == "new_account":
            call("create_account", p)
        elif k == "admin_access":
            call("grant_role", p)
        elif k == "offboard":
            call("revoke_role", p)
        elif k in ("send_contract", "send_nda", "data_request"):
            call("share_doc_external", p)
        elif k == "edit_contract":
            call("edit_contract", p)
        elif k in ("sales_quote", "sales_discount"):
            call("update_crm", p)
        elif k in ("month_close", "circulate_agenda"):
            call("send_email", p)
        elif k == "approve_payment":
            return
        else:
            return
        call("close_ticket", {"id": t["id"], "note": "done"})


def make_team(cls, day=None):
    return {s: cls() for s in SEATS}
