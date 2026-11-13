import glob
import json
import os
import sys


def export(run_dir, out):
    os.makedirs(out, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(run_dir, "days", "*.json"))):
        d = json.load(open(p))
        r = d["result"]
        team = r.get("team") or r["agent"]
        i = f"{team}-{r['day_id']}-t{r['trial']}"
        day = dict(d["day"])
        day["seed"] = r["day_id"]
        with open(os.path.join(out, i + ".json"), "w") as f:
            json.dump({"id": i, "day": day, "messages": d["messages"], "actions": d["ledger"], "result": [r]}, f)


if __name__ == "__main__":
    export(sys.argv[1], sys.argv[2])
