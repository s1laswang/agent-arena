import json, gzip, collections, os
R = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT = os.path.dirname(os.path.abspath(__file__))
MODEL = "gemini-3.5-flash"
LEVELS = ["minimal", "low", "medium", "high"]
SEEDS = [0, 1, 3, 5, 8]
LADDER = json.load(open(f"{R}/results/gemini/ladder.json"))
P = LADDER["prices_usd_per_1m"][MODEL]
EPS = f"results/gemini/ladder_episodes.jsonl.gz"

def dump(name, obj):
    json.dump(obj, open(f"{OUT}/{name}", "w"), indent=1)

solver = {}
for p in ["solver-hard-20261114-121126", "solver-hard-seeds20to29"]:
    for l in open(f"{R}/data/runs/committed/v1.4/reference/{p}/episodes.jsonl"):
        e = json.loads(l)
        solver[e["seed"]] = e

eps = collections.defaultdict(dict)
for l in gzip.open(f"{R}/{EPS}", "rt"):
    e = json.loads(l)
    if e["agent"] == "gemini:" + MODEL and e["tier"] == "hard" and e["seed"] in SEEDS:
        eps[e["seed"]][e["meta"]["ladder"]["level"]] = e

def cost(t):
    return round(((t["in"] - t["cached"]) * P[0] + t["cached"] * P[2] + (t["out"] + t["thinking"]) * P[1]) / 1e6, 4)

def evidence(e):
    emp, canaries, feed, interviews, msgs, ah = None, [], [], [], [], collections.Counter()
    seen = set()
    for s in e["steps"]:
        d = (s["result"] or {}).get("data") or {}
        if s["tool"] == "list_employees":
            emp = d["employees"]
        elif s["tool"] == "plant_canary" and d.get("canary_id"):
            g = collections.defaultdict(list)
            for k, v in s["args"]["assignment"].items():
                g[v].append(k)
            canaries.append({"canary_id": d["canary_id"], "day": s["day"], "title": s["args"].get("doc_title"), "groups": dict(sorted(g.items()))})
        elif s["tool"] == "check_leak_feed":
            feed = d.get("items", [])
        elif s["tool"] == "interview" and d:
            interviews.append({"day": s["day"], "employee": s["args"].get("employee"), "topic": s["args"].get("topic"), "result": d})
        elif s["tool"] in ("search_messages", "read_message") and d.get("messages"):
            for m in d["messages"]:
                if m["id"] not in {x["id"] for x in msgs}:
                    msgs.append(m)
        elif s["tool"] == "read_access_logs":
            for r in d.get("logs", []):
                k = (r["day"], r["doc_id"], r["employee"], r["after_hours"])
                if k not in seen:
                    seen.add(k)
                    if r["after_hours"]:
                        ah[r["employee"]] += 1
    return emp, canaries, feed, interviews, msgs, ah

def consistent(canaries, feed, emp):
    ids = {x["doc_id"]: x for x in feed if x.get("variant")}
    pool = {x["id"] for x in emp}
    cs = {c["canary_id"]: c for c in canaries}
    for did, x in ids.items():
        if did in cs:
            pool &= set(cs[did]["groups"].get(x["variant"], []))
    return sorted(pool), len(ids)

rounds = []
for n, seed in enumerate(SEEDS, 1):
    hi = eps[seed]["high"]
    emp, canaries, feed, interviews, msgs, ah = evidence(hi)
    name = {x["id"]: x for x in emp}
    last_day = hi["final_day"]
    feed_shown = [x for x in feed if x["surfaced_day"] <= last_day]
    pool, nvar = consistent(canaries, feed_shown, emp)
    sol = solver[seed]
    mole = sol["accused"]
    assert sol["correct"]
    lv = []
    for L in LEVELS:
        e = eps[seed][L]
        t = e["meta"]["ladder"]["tokens"]
        lv.append({"level": L, "accused": e["accused"], "accused_name": name[e["accused"]]["name"], "correct": e["correct"], "score": round(e["score"], 3),
                   "accuse_day": e["final_day"], "calls": t["calls"], "tokens_in": t["in"], "tokens_cached": t["cached"], "tokens_out": t["out"],
                   "tokens_thinking": t["thinking"], "cost_usd": cost(t), "run_id": e["meta"]["ladder"]["run_id"]})
    rounds.append({
        "round": n, "tier": "hard", "seed": seed, "tiers_version": "v1.4", "company_size": len(emp),
        "evidence_source_level": "high", "evidence_day": last_day,
        "employees": emp, "canaries": canaries, "leak_feed": feed_shown,
        "interviews": interviews, "messages": msgs,
        "after_hours_counts_seen": dict(ah.most_common()),
        "variant_consistent_pool": pool, "leaked_variants_counted": nvar,
        "mole": mole, "mole_name": name[mole]["name"], "mole_basis": "reference solver accused it and was correct on this seed",
        "levels": lv,
        "solver": {"accused": sol["accused"], "correct": sol["correct"], "score": round(sol["score"], 3), "accuse_day": sol["final_day"]},
        "wait_score": 0.0
    })
dump("rounds.json", {"source": ["results/gemini/ladder_episodes.jsonl.gz (evidence, level choices, tokens)", "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl (solver)", "results/gemini/ladder.json prices_usd_per_1m (cost)"],
    "model_served_as": "gemini-3.5-flash is served as gemini-3.6-flash; say 3.6-flash on screen", "cost_formula": "((tokens_in - tokens_cached)*in + tokens_cached*cached + (tokens_out + tokens_thinking)*out)/1e6 at prices_usd_per_1m", "prices_usd_per_1m_in_out_cached": P,
    "note": "variant_consistent_pool is derived: employees who got the leaked variant on every leaked canary shown; leak fingerprint is 95% accurate on hard so it can miss the mole", "rounds": rounds})

rows = []
for r in LADDER["rows"]:
    if r["tier"] == "hard":
        rows.append({k: r[k] for k in ["model", "level", "n", "mean", "ci", "accuracy", "accuse_day", "solver_same_seeds", "ratio", "ratio_lo", "ratio_hi", "cost_per_ep"]})
dump("levels.json", {"source": "results/gemini/ladder.json rows (tier hard); rendered in results/gemini/ladder.md", "ratio": "mean score / reference solver mean on the same seeds; ratio_lo/hi is a 95% bootstrap CI", "rows": rows})

dump("reference.json", {"source": "results/gemini/ladder.json reference", "rows": LADDER["reference"],
    "solver_per_seed_source": "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl and solver-hard-seeds20to29/episodes.jsonl",
    "solver_seeds_used": {str(s): {"accused": solver[s]["accused"], "score": round(solver[s]["score"], 3), "accuse_day": solver[s]["final_day"]} for s in SEEDS}})

g = json.load(open(f"{R}/results/gemini/failure_gallery.json"))
dump("failure_modes.json", {"source": "results/gemini/failure_gallery.json (rendered in docs/reports/failure_gallery.md)", "net_gap_total": g["net_gap"], "episodes_decomposed": g["episodes_decomposed"],
    "cards": [{k: c[k] for k in ["category", "name", "kind", "explanation", "value", "share_of_net_gap", "episodes"]} for c in g["cards"]]})

dump("totals.json", {"source": "four committed files, they disagree because each counts a different set of calls and a different price basis; the game must show one number and cite its file",
    "figures": [
        {"file": "results/gemini/dashboard.html (embedded usage.totals), same as docs/gemini/SUBMISSION.md", "calls": 24855, "cost_usd": 226.337, "basis": "usage ledger, list price"},
        {"file": "results/gemini/ladder.md and ladder.json ledger", "calls": 36164, "cost_usd_ledger": 236.27, "cost_usd_list_price": 298.75, "basis": "ladder ledger only, 618 run ids"},
        {"file": "results/gemini/ablations.md and docs/gemini/SUBMISSION.md", "calls": 29150, "cost_usd_paid": 214.89, "cost_usd_no_cache_counterfactual": 893.08, "cache_saved_pct": 75.9, "basis": "programme-wide, paid vs all input at full price"},
        {"file": "results/gemini/usage_ledger.jsonl.gz (summed cost_usd)", "calls": 24855, "cost_usd": 198.71, "basis": "row-wise cost_usd field, differs from dashboard 226.34"}],
    "missing": "results/gemini/usage_total.json does not exist",
    "recommended_for_game": "use per-episode cost from rounds.json; if a total is shown, cite dashboard.html 24,855 calls and $226.34"})

dump("rules.json", {"source": "docs/CONTRACT.md and canary/rules.py (v1.4)",
    "score": {"correct_accusation": "true company value V at accusation time", "wrong_accusation": -1, "no_accusation": 0}, "accuse_once": True,
    "hard": {"employees": 40, "days": 21, "tool_call_cap": 420, "actions_per_day": 8, "max_variants": 3, "canaries_per_day": 2, "fingerprint_accuracy": 0.95, "leak_delay_days": "surfaces some days after the leak"},
    "tools": ["status", "list_employees", "list_documents", "read_access_logs", "search_messages", "read_message", "interview", "plant_canary", "check_leak_feed", "restrict_access", "unrestrict_access", "advance_day", "accuse"],
    "levels": LEVELS, "model": MODEL, "model_served_as": "gemini-3.6-flash"})
