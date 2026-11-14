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
