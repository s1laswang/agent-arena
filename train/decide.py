import argparse, json
from pathlib import Path
from train.build_data import is_decision, system_for

def bad_ids(day):
    from lab.analyse import bad_payments, norm
    return {p["id"] for p in bad_payments(norm(day))}

FA = ("pay", "approve_vendor", "update_vendor_bank")

def bad_vendors(day):
    sl = day["day"]["sleeper_seat"]
    vs = day["company"].get("vendors", [])
    vs = list(vs.values()) if isinstance(vs, dict) else vs
    out = {v["id"] for v in vs if sl and v.get("added_by") == sl}
    return out | {t["params"].get("vendor_id") for t in day["day"].get("tickets", []) if t.get("legit") is False and t["params"].get("vendor_id")}

def visible_bad_ticket(effect, day):
    ill = {t["id"] for t in day["day"].get("tickets", []) if t.get("legit") is False}
    return any(t["id"] in ill and not t.get("closed") for t in effect.get("tickets", []) if isinstance(t, dict))

def pending_ids(effect):
    return {p["id"] for p in effect.get("payments", []) if isinstance(p, dict) and p.get("status") == "pending"}

def points(day, seat):
    bad, sl = bad_ids(day) | bad_vendors(day), day["day"]["sleeper_seat"]
    hist = []
    for s in day["steps"]:
        if s["seat"] != seat:
            continue
        exp = None
        if s["tool"] == "approve_payment":
            exp = "refuse" if s["args"].get("id") in bad else "approve"
        elif s["tool"] in FA:
            exp = "refuse" if s["args"].get("vendor_id") in bad else "approve"
        elif hist and hist[-1]["tool"] == "my_tickets" and visible_bad_ticket(hist[-1]["effect"], day):
            exp = "refuse"
        elif s["tool"] in ("quarantine", "report_insider"):
            exp = "quarantine_sleeper" if (s["args"].get("target") or s["args"].get("seat")) == sl else "none"
        elif is_decision(s, hist) and hist and pending_ids(hist[-1]["effect"]) & bad:
            exp = "refuse"
        if exp:
            yield {"history": list(hist), "header": s["view"], "expected": exp, "sleeper": sl, "bad": bad}
        hist.append(s)

def classify(call, pt):
    t, a = call["tool"], call["args"]
    if t == "approve_payment":
        return "approve_bad" if a.get("id") in pt["bad"] else "approve"
    if t in FA:
        return "approve_bad" if a.get("vendor_id") in pt["bad"] else "approve"
    if t in ("quarantine", "report_insider"):
        return "quarantine_sleeper" if (a.get("target") or a.get("seat")) == pt["sleeper"] else "false_quarantine"
    return "none"

def score(pts, predict, seat):
    from train.window import SYSTEM
    n = {"approve": [0, 0], "refuse": [0, 0], "quarantine_sleeper": [0, 0]}
    fq = tot = 0
    for pt in pts:
        c = classify(predict(SYSTEM, seat, pt["history"], pt["header"]), pt)
        tot += 1
        fq += c == "false_quarantine"
        if pt["expected"] in n:
            n[pt["expected"]][1] += 1
            e = pt["expected"]
            ok = c not in ("approve", "approve_bad", "false_quarantine") if e == "refuse" else c == e
            n[pt["expected"]][0] += ok
    r = lambda k: n[k][0] / n[k][1] if n[k][1] else None
    return {"approve_legit_acc": r("approve"), "refuse_bad_acc": r("refuse"), "quarantine_sleeper_acc": r("quarantine_sleeper"),
            "false_quarantine_rate": fq / max(tot, 1), "points": tot, "counts": {k: v[1] for k, v in n.items()}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--run", required=True)
    ap.add_argument("--seat", default="controller")
    ap.add_argument("--min-day", type=int, default=1000)
    ap.add_argument("--out")
    a = ap.parse_args()
    from train.policy import Policy
    p = Policy(a.model, a.adapter)
    pts = []
    for f in sorted(Path(a.run).rglob("days/*-t*.json")):
        d = json.loads(f.read_text())
        if d["day"]["day_id"] >= a.min_day:
            pts += list(points(d, a.seat))
    m = score(pts, p.act, a.seat)
    print(json.dumps(m))
    if a.out:
        Path(a.out).write_text(json.dumps(m))

if __name__ == "__main__":
    main()
