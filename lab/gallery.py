import json
import sys
from pathlib import Path

from lab import analyse, report


def trigger(day, fl):
    a = next(x for x in day["ledger"] if x["seq"] == fl["action_seq"])
    ms = [m for m in (day.get("messages") or day["company"].get("messages", [])) if m["tick"] <= a["tick"] and fl["seat"] in m["to"] and m["sender_seat"] != fl["seat"]]
    m = ms[-1] if ms else None
    return a, ({"from": m["sender_seat"], "channel": m["channel"], "subject": m.get("subject"), "body": m["body"]} if m else None)


def gallery(run_dir):
    run_dir = Path(run_dir)
    best = {}
    for d in analyse.load(run_dir):
        for fl in analyse.label(d):
            if fl["action_seq"] is None or fl["label"] not in analyse.GLOSSARY:
                continue
            a, t = trigger(d, fl)
            size = len(json.dumps(a["args"])) + len(fl["evidence"]) + (len(t["body"]) if t else 400)
            if fl["label"] not in best or size < best[fl["label"]][0]:
                best[fl["label"]] = (size, fl, a, t)
    out = []
    for lab, (_, fl, a, t) in sorted(best.items()):
        f = run_dir / "days" / f"{fl['day_id'].lstrip('d')}-t{fl['trial']}.json"
        out.append({"label": lab, "day_id": fl["day_id"], "trial": fl["trial"], "seat": fl["seat"], "trigger": t, "decisive_action": {"seq": a["seq"], "tool": a["tool"], "args": a["args"]},
                    "what_went_wrong": fl["evidence"], "oracle_evidence": analyse.GLOSSARY[lab][1], "decision": analyse.GLOSSARY[lab][0], "replay": f"python -m lab.replay {f} --seq {a['seq']}"})
    return out


def md(g):
    L = ["# Failure gallery", "", "One short example per named failure of the scripted staff team.", ""]
    for x in g:
        t = x["trigger"]
        L += [f"## {x['label']}", f"Day {x['day_id']} trial {x['trial']}, seat {x['seat']}.", "", f"- Trigger: " + (f"{t['from']} ({t['channel']}): {t['body']}" if t else "none, the seat acted on its own"),
              f"- Decisive action: {x['decisive_action']['tool']} {json.dumps(x['decisive_action']['args'])}", f"- What went wrong: {x['what_went_wrong']}", f"- The oracle instead: {x['oracle_evidence']}", f"- Replay: `{x['replay']}`", ""]
    return "\n".join(L)


def main(eval_dir):
    eval_dir = Path(eval_dir)
    rs = report.runs(eval_dir)
    st = report.pick(rs, "staff")
    g = gallery(st[0]) if st else []
    (eval_dir / "gallery.json").write_text(json.dumps(g, indent=2))
    (eval_dir / "gallery.md").write_text(md(g))
    return g


if __name__ == "__main__":
    print(len(main(sys.argv[1])), "examples")
