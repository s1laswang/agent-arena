import sys
from collections import Counter
from unittest import mock

from lab import analyse
from lab import run as lrun


def swap(team, day_id, trial, seat):
    orig = lrun.build_team

    def build(name, day, t):
        players = orig(name, day, t)
        if name == team:
            players[seat] = orig("oracle", day, t)[seat]
        return players

    with mock.patch.object(lrun, "build_team", build):
        res, _ = lrun.play_day(team, team, None, day_id, trial)
    return res["reward"]


def counterfactual(run_dir, team="staff"):
    per_label, losses, fixed = Counter(), 0, 0
    flipped_label = Counter()
    for day in analyse.load(run_dir):
        r = day["result"]
        if r["reward"] != 0:
            continue
        losses += 1
        fls = analyse.label(day)
        cache, any_flip = {}, False
        for x in fls:
            per_label[x["label"]] += 1
            s = x["seat"]
            if s is None or s == day.get("sleeper_seat"):
                continue
            if s not in cache:
                cache[s] = swap(team, int(str(r["day_id"]).lstrip("d")), r.get("trial", 0), s)
            if cache[s]:
                flipped_label[x["label"]] += 1
                any_flip = True
        fixed += any_flip
    return {"losses": losses, "fixed": fixed, "labels": {k: (n, flipped_label[k]) for k, n in sorted(per_label.items())}}


def table(c):
    pct = 100 * c["fixed"] / c["losses"] if c["losses"] else 0
    lines = ["| label | decisions | fixed by one careful seat |", "|---|---|---|"]
    lines += [f"| {k} | {n} | {f} |" for k, (n, f) in c["labels"].items()]
    lines += ["", f"{c['fixed']} of {c['losses']} lost days ({pct:.0f}%) flip to reward 1 when the one seat that made the decisive decision follows the oracle procedure, using only tools already available."]
    return "\n".join(lines)


if __name__ == "__main__":
    print(table(counterfactual(sys.argv[1])))
