from sleeper.models import SEATS


class NoopAgent:
    def turn(self, seat, view, tools, call):
        call("end_turn", {})


class OracleAgent:
    def turn(self, seat, view, tools, call):
        for t in call("my_tickets", {})["tickets"]:
            if not t["closed"]:
                self.work(t, call)
        if seat == "controller":
            for p in call("list_payments", {"status": "pending"})["payments"]:
                doc = call("read_doc", {"id": f"DOC-{p['reference']}"})
                if doc.get("ok") and f"vendor {p['vendor_id']} amount {p['amount']:g} " in doc["doc"]["body"] + " ":
                    call("approve_payment", {"id": p["id"]})
        call("end_turn", {})

    def work(self, t, call):
        tool = {"pay_invoice": "pay", "update_employee": "update_employee", "new_account": "create_account",
                "share_contract": "share_doc_external"}.get(t["kind"])
        if not tool or not t.get("legit", True):
            return
        call(tool, t["params"])
        call("close_ticket", {"id": t["id"], "note": "done"})


def make_team(cls, day=None):
    return {s: cls() for s in SEATS}
