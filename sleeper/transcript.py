import argparse
import json

from sleeper.day import run_day
from sleeper.scripted import NoopAgent, OracleAgent, make_team
from sleeper.tickets import make_day
from sleeper.verifier import score

TEAMS = {"oracle": OracleAgent, "noop": NoopAgent}


def transcript(world):
    rows = []
    for i, m in enumerate(world.company.messages):
        rows.append(((m.tick, 0, i), {"tick": m.tick, "seat": m.sender_seat, "type": "message", "channel": m.channel,
                                      "to": m.to, "body": m.body}))
    for a in world.ledger:
        rows.append(((a.tick, 1, a.seq), {"tick": a.tick, "seat": a.seat, "type": "action", "tool": a.tool,
                                          "args": a.args, "ok": a.ok, "effect": a.effect}))
    return [r for _, r in sorted(rows, key=lambda x: x[0])]


def write(world, path):
    with open(path, "w") as f:
        for r in transcript(world):
            f.write(json.dumps(r) + "\n")


def line(r):
    if r["type"] == "message":
        return f"t{r['tick']} {r['seat']} -> {','.join(r['to'])} [{r['channel']}] {r['body'][:80]}"
    return f"t{r['tick']} {r['seat']} {r['tool']} {'ok' if r['ok'] else 'FAIL'} {r['effect']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--team", choices=sorted(TEAMS), default="oracle")
    ap.add_argument("--out")
    a = ap.parse_args()
    day = make_day(a.seed)
    w = run_day(day, make_team(TEAMS[a.team]))
    if a.out:
        write(w, a.out)
    for r in transcript(w):
        if r.get("tool") != "end_turn":
            print(line(r))
    print(score(day, w.initial, w.company, w.ledger, agent=a.team).model_dump_json())


if __name__ == "__main__":
    main()
