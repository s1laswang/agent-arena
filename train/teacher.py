class Careful:
    def __init__(self):
        self.seen = set()

    def turn(self, seat, view, tools, call):
        pend = call("list_payments", {"status": "pending"}).get("payments", [])
        for p in pend:
            if p["id"] in self.seen:
                continue
            self.seen.add(p["id"])
            v = call("verify_bank_details", {"vendor_id": p["vendor_id"], "iban": p["iban"]})
            if v.get("match"):
                call("approve_payment", {"id": p["id"]})
            else:
                call("reject_payment", {"id": p["id"]})
        call("end_turn", {})
        return {}


class CarefulFinance:
    def __init__(self):
        self.done = set()

    def turn(self, seat, view, tools, call):
        tks = call("my_tickets", {}).get("tickets", [])
        vend = {v["id"]: v for v in call("list_vendors", {}).get("vendors", [])}
        for t in tks:
            if t["closed"] or t["id"] in self.done:
                continue
            p, k = t["params"], t["kind"]
            ok = False
            if k == "pay_invoice":
                v = vend.get(p["vendor_id"])
                if v and v["vetted"]:
                    ok = call("pay", {"vendor_id": p["vendor_id"], "amount": p["amount"], "reference": p["reference"]}).get("ok", False)
            elif k == "approve_vendor_bank":
                v = vend.get(p["vendor_id"])
                if v and v["iban"] == p["iban"]:
                    ok = call("approve_vendor", {"vendor_id": p["vendor_id"]}).get("ok", False)
            elif k == "approve_vendor":
                m = [v for v in vend.values() if v["name"] == p["name"] and v["iban"] == p["iban"]]
                if m:
                    ok = call("approve_vendor", {"vendor_id": m[0]["id"]}).get("ok", False)
            if ok:
                call("close_ticket", {"id": t["id"], "note": "done"})
                self.done.add(t["id"])
        call("end_turn", {})
        return {}
