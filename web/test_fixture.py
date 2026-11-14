import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sleeper.models import Action, Day, Message, Result

files = [f for f in glob.glob(str(Path(__file__).parent / "days" / "*.json")) if not f.endswith(("index.json", "live.json"))]
assert files
ids = set()
for f in files:
    d = json.load(open(f))
    day = Day.model_validate(d["day"])
    [Message.model_validate(m) for m in d["messages"]]
    [Action.model_validate({k: v for k, v in a.items() if k != "harmful"}) for a in d["actions"]]
    [Result.model_validate(r) for r in d["result"]]
    assert d["id"] == Path(f).stem
    ids.add(d["id"])
rows = json.load(open(Path(__file__).parent / "days" / "index.json"))
assert {r["id"] for r in rows} == ids
print("ok")

import re

f = Path(__file__).parent / "days" / "1-staff.json"
if f.exists():
    d = json.load(open(f))
    pay = next(a for a in d["actions"] if a.get("harmful") and a["ok"] and a["tool"] == "pay")
    if "paid" in pay["effect"]:
        money = pay
    else:
        pid = re.search(r"P\d+", pay["effect"]).group(0)
        money = next(a for a in d["actions"] if a["tool"] == "approve_payment" and a["ok"] and a["seq"] > pay["seq"] and a["args"].get("id") == pid)
    assert money["tick"] >= pay["tick"]
    assert d["result"][0]["reward"] == 0 and d["result"][0]["harm"]
print("ok money")
