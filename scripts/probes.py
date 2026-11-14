import argparse, glob, json, multiprocessing, os, random, subprocess

os.environ["GEMINI_API_KEY"] = ""
os.environ["LAB_GEMINI"] = "0"

from lab import run
from sleeper.baselines import SEATS, register, work
from sleeper.company import tools_for

DAYS = (1000,)
CAPS = {}
READ = ("read_", "list_", "search_", "my_", "get_")


class Cap:
    def __init__(self, inner, cap):
        self.inner, self.cap, self.n = inner, cap, 0

    def turn(self, seat, view, tools, call):
        def capped(tool, args=None):
            if tool != "end_turn":
                if self.n >= self.cap:
                    return {"ok": False, "error": "stopped"}
                self.n += 1
            return call(tool, args or {})

        self.inner.turn(seat, view, tools, capped)


class Pad:
    def __init__(self, inner):
        self.inner, self.done = inner, False

    def turn(self, seat, view, tools, call):
        if not self.done:
            self.done = True
            for _ in range(50):
                call("my_tickets", {})
        self.inner.turn(seat, view, tools, call)


class Fn:
    def __init__(self, f, day, seed):
        self.f, self.day, self.rng = f, day, random.Random(seed)

    def turn(self, seat, view, tools, call):
        self.f(self, seat, view, call)
        call("end_turn", {})


def names(seat):
    return [t["name"] for t in tools_for(seat) if t["name"] != "end_turn"]


def args_for(seat, name, rng):
    props = next(t for t in tools_for(seat) if t["name"] == name)["parameters"]["properties"]
    return {k: ["x"] if v["type"] == "array" else 1 if v["type"] == "number" else {} if v["type"] == "object" else rng.choice(["x", "T001", "V01"]) for k, v in props.items()}


def f_random(s, seat, view, call):
    ns = names(seat)
    for _ in range(10):
        n = s.rng.choice(ns)
        call(n, args_for(seat, n, s.rng))


def f_probe_all(s, seat, view, call):
    for n in names(seat):
        if n.startswith(READ):
            call(n, {})


def f_malformed(s, seat, view, call):
    for n in names(seat):
        for a in ({}, {"id": None, "body": 7, "to": "", "target": 3, "amount": "abc"}, {"x" * 50: "y" * 5000}):
            call(n, a)


def f_decoy(s, seat, view, call):
    work(seat, call)
    t = next(x for x in SEATS if x not in (s.day.sleeper_seat, seat))
    call("quarantine", {"target": t})


def f_dup(s, seat, view, call):
    for _ in range(5):
        call("quarantine", {"target": s.day.sleeper_seat or next(x for x in SEATS if x != seat)})


def f_over(s, seat, view, call):
    for _ in range(260):
        call("my_tickets", {})


FNS = {"random_calls": f_random, "probe_all": f_probe_all, "malformed_args": f_malformed, "accuse_decoy": f_decoy, "dup_accuse_no_work": f_dup, "over_budget": f_over}
BASE = ("do_nothing", "refuse_all", "quarantine_all", "claim_only")
CUTS = (0.25, 0.5, 0.75)


def team_of(name):
    def make(day, trial):
        if name in FNS:
            return {s: Fn(FNS[name], day, f"{name}-{day.seed}-{s}") for s in SEATS}
        base = run.build_team("oracle", day, trial)
        if name == "control_pad":
            return {s: Pad(a) for s, a in base.items()}
        frac = float(name.split("@")[1])
        return {s: Cap(a, int(frac * CAPS.get((MODE[0], day.seed, s), 0))) for s, a in base.items()}

    return make


MODE = [None]
PROBES = list(BASE) + [f"stop_ref@{c}" for c in CUTS] + list(FNS) + ["control_pad"]


def play(a):
    probe, mode, d = a
    key = probe if probe in BASE else "p_" + probe
    seat = "finance_ap" if mode == "seat" else None
    MODE[0] = mode
    r, x = run.play_day("oracle" if seat else key, key, seat, d, 0)
    return probe, mode, d, r["reward"], x


def ref_calls(a):
    mode, d = a
    seat = "finance_ap" if mode == "seat" else None
    _, x = run.play_day("oracle", "oracle", seat, d, 0)
    out = {}
    for st in x["steps"]:
        if st["tool"] != "end_turn":
            out[st["seat"]] = out.get(st["seat"], 0) + 1
    return mode, d, out


def replay(root="results"):
    from sleeper.models import Action
    from sleeper.company import Company, seed_company
    from sleeper.verifier import score

    n = bad = 0
    out = []
    for f in sorted(glob.glob(root + "/**/days/*.json", recursive=True)):
        try:
            d = json.load(open(f))
            res = d["result"]
            seat = res.get("seat_under_test")
            day, *_ = run.day_for(res["day_id"] if isinstance(res["day_id"], int) else res["seed"], seat)
            r = score(day, seed_company(day.seed), Company.model_validate(d["company"]), [Action.model_validate(x) for x in d["ledger"]], seat_under_test=seat)
        except Exception as e:
            out.append(f"{f}: replay error {type(e).__name__}")
            bad += 1
            n += 1
            continue
        n += 1
        if r.reward != res["reward"]:
            bad += 1
            out.append(f"{f}: stored {res['reward']} rescored {r.reward}")
    return n, bad, out


def table(days=DAYS, jobs=4):
    register()
    for p in PROBES:
        if p not in BASE:
            run.FACTORIES["p_" + p] = (team_of(p), "scripted")
    run.TEAMS[:] = list(run.FACTORIES)
    ctx = multiprocessing.get_context("fork")
    modes = ("seat", "team")
    with ctx.Pool(jobs) as pool:
        for mode, d, c in pool.map(ref_calls, [(m, d) for m in modes for d in days]):
            for s, k in c.items():
                CAPS[(mode, d, s)] = k
    with ctx.Pool(jobs) as pool:
        res = pool.map(play, [(p, m, d) for p in PROBES for m in modes for d in days])
    from agents import gemini

    assert gemini.usage()["calls"] == 0, gemini.usage()
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    rows = []
    for p in PROBES:
        row = {"probe": p, "commit": commit}
        for m in modes:
            rs = [r for q, mm, d, r, _ in res if q == p and mm == m]
            row[m] = {"n": len(rs), "reward_mean": round(sum(rs) / len(rs), 3)}
        rows.append(row)
    return rows


def md(rows):
    ls = ["| probe | finance_ap n | finance_ap reward | team n | team reward | commit |", "|---|---|---|---|---|---|"]
    ls += [f"| {r['probe']} | {r['seat']['n']} | {r['seat']['reward_mean']} | {r['team']['n']} | {r['team']['reward_mean']} | {r['commit']} |" for r in rows]
    return "\n".join(ls)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=len(DAYS))
    ap.add_argument("--start", type=int, default=1000)
    a = ap.parse_args(argv)
    rows = table(tuple(range(a.start, a.start + a.days)))
    n, bad, out = replay()
    print(md(rows))
    print(f"\nreplay: {n} committed run files rescored, {bad} mismatches")
    print(*out, sep="\n")
    os.makedirs("results", exist_ok=True)
    open("results/probes.md", "w").write(md(rows) + f"\n\nreplay: {n} rescored, {bad} mismatches\n")
    json.dump(rows, open("results/probes.json", "w"), indent=1)


if __name__ == "__main__":
    main()
