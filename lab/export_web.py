import glob
import json
import os
import sys


def export(run_dir, out):
    os.makedirs(out, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(run_dir, "days", "*.json"))):
        d = json.load(open(p))
        r = d["result"]
        i = f"{r.get('team') or r['agent']}-{r['seed']}-t{r['trial']}"
        bad = set(d.get("harmful", []))
        r = {**r, "transcript_path": f"web/days/{i}.json"}
        doc = {"id": i, "day": d["day"], "messages": d["messages"], "actions": [{**a, "harmful": a["seq"] in bad} for a in d["ledger"]], "result": [r], "quarantined": d["company"]["quarantined"]}
        with open(os.path.join(out, i + ".json"), "w") as f:
            json.dump(doc, f)


if __name__ == "__main__":
    export(sys.argv[1], sys.argv[2])
