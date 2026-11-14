import json
import sys

from lab import analyse


def replay(day, seq, span=6):
    day = analyse.norm(day)
    a = next(x for x in day["ledger"] if x["seq"] == seq)
    fl = [x for x in analyse.label(day) if x["action_seq"] == seq]
    out = [f"day {day['result']['day_id']} trial {day['result'].get('trial', 0)}  decisive action seq {seq}: {a['seat']} {a['tool']} {json.dumps(a['args'])}"]
    out += [f"LABEL {x['label']}: {x['evidence']}" for x in fl]
    out.append("-- chat before --")
    chat = [x for x in day["ledger"] if x["tool"] == "post_chat" and x["seq"] <= seq]
    out += [f"  seq {x['seq']} t{x['tick']} {x['seat']} -> {x['args'].get('to')}: {x['args'].get('body')}" for x in chat[-3:]]
    out.append("-- ledger around --")
    out += [f"{'>>' if x['seq'] == seq else '  '} seq {x['seq']} t{x['tick']} {x['seat']} {x['tool']} {json.dumps(x['args'])} ok={x['ok']} {x['effect']}" for x in day["ledger"] if abs(x["seq"] - seq) <= span]
    return "\n".join(out)


if __name__ == "__main__":
    seq = int(sys.argv[sys.argv.index("--seq") + 1])
    print(replay(json.load(open(sys.argv[1])), seq))
