import json,sys,glob
SEATS={"ceo_assistant","finance_ap","controller","hr","it_admin","procurement","sales","legal"}
for f in glob.glob("days/*.json"):
    d=json.load(open(f))
    assert {"seed","sleeper_seat","goal"}<=set(d["day"])
    for m in d["messages"]:assert {"id","tick","sender_seat","to","channel","body","attachments"}<=set(m) and m["sender_seat"] in SEATS
    for a in d["actions"]:assert {"seq","tick","seat","tool","args","ok","effect"}<=set(a) and a["seat"] in SEATS
    for r in d["result"]:assert {"day_id","seed","seat_under_test","agent","model","reward","tickets_done","tickets_total","harm","false_quarantine","sleeper_caught","steps","transcript_path"}<=set(r)
    assert d["day"]["sleeper_seat"] is None or d["day"]["sleeper_seat"] in SEATS
    assert all(sum(a["seat"]==s for a in d["actions"])<=60 for s in SEATS)
print("ok")
