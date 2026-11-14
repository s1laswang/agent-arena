"""Does any measured Gemini loss hinge on the careful-mole wording (DIFFICULTY.md, known wording issue W1)?

    uv run python scripts/careful_mole_check.py     # prints the table quoted in docs/DIFFICULTY.md (no keys, seconds)

For OpenCode gemini-4-carbon and the reference solver on v1.4 hard seeds 0-29 (committed episodes), replays each
episode and reports how the agent sized its canaries (share of staff per canary -> careful weight 1 - share) and how
often its canaries leaked, and counts the Gemini transcripts that discuss the careful rule.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary.env import Env  # noqa: E402

V14 = ROOT / "data/runs/committed/v1.4"
RUNS = {"Gemini (OpenCode/MCP)": [V14 / "opencode-gemini-4-carbon/hard/episodes.jsonl"],
        "solver": [V14 / "reference/solver-hard-20261114-121126/episodes.jsonl",
                   V14 / "reference/solver-hard-seeds20to29/episodes.jsonl"]}
TRANSCRIPTS = V14 / "opencode-gemini-4-carbon/hard/transcripts"
CAREFUL = re.compile(r"careful|1\s*-\s*the share|\(1 - share|weight", re.I)


def stats(paths):
    eps = [json.loads(l) for p in paths for l in p.read_text().splitlines() if l.strip()]
    eps = [e for e in eps if e["tier"] == "hard" and e["seed"] < 30]
    shares, n_can, can_leaks, leaks, per_seed = [], 0, 0, 0, {}
    exp_careful = exp_uniform = 0.0
    for e in eps:
        env = Env("hard", e["seed"])
        views = []
        orig = env._mole_view  # noqa: SLF001

        def hook(d, _orig=orig, _views=views):
            v = _orig(d)
            _views.append(v)
            return v
        env._mole_view = hook  # noqa: SLF001
        for s in e["steps"]:
            if env.done:
                break
            env.call(s["tool"], s.get("args") or {})
        cans = {d: x for d, x in env._doc_by_id.items() if x.get("is_canary")}  # noqa: SLF001
        # expected canary picks on the days the mole leaked (p_leak gate passed), careful weights vs uniform
        ec = eu = 0.0
        for v in views:
            if not (v.can_leak and v.docs):
                continue
            isc = [d.doc_id in cans for d in v.docs]
            w = v.select_weights or tuple(1.0 for _ in v.docs)
            if sum(w) > 0:
                ec += sum(wi for wi, c in zip(w, isc) if c) / sum(w)
            eu += sum(isc) / len(isc)
        exp_careful += ec
        exp_uniform += eu
        sh = [len(x["recipients"]) / env.p.n_employees for x in cans.values()]
        shares += sh
        lk = [x for x in env.ledger() if x.event == "leak"]
        cl = sum(1 for x in lk if x.detail["doc_id"] in cans)
        n_can += len(cans)
        can_leaks += cl
        leaks += len(lk)
        per_seed[e["seed"]] = {"canaries": len(cans), "max_share": round(max(sh, default=0), 3), "canary_leaks": cl,
                               "exp_canary_leaks_careful": round(ec, 2), "exp_canary_leaks_uniform": round(eu, 2)}
    return {"n": len(eps), "share_mean": sum(shares) / len(shares), "share_max": max(shares),
            "exp_careful": exp_careful, "exp_uniform": exp_uniform,
            "weight_mean": sum(1 - x for x in shares) / len(shares), "canaries": n_can,
            "canary_leaks": can_leaks, "leaks": leaks, "per_seed": per_seed}


def main() -> int:
    res = {k: stats(v) for k, v in RUNS.items()}
    print("| agent | canaries | mean share of staff per canary | largest | mean careful weight (1 − share) | "
          "canary leaks / canaries planted | canary leaks / all leaks |")
    print("|---|---|---|---|---|---|---|")
    for k, r in res.items():
        print(f"| {k} | {r['canaries']} | {r['share_mean']:.2f} | {r['share_max']:.2f} | {r['weight_mean']:.2f} | "
              f"{r['canary_leaks']}/{r['canaries']} = {r['canary_leaks'] / r['canaries']:.2f} | "
              f"{r['canary_leaks']}/{r['leaks']} = {r['canary_leaks'] / r['leaks']:.2f} |")
    print("\nExpected canary leaks on the agent's own trajectory (days the p_leak gate passed): careful weights vs "
          "all weights 1, i.e. what the careful rule costs that agent's canaries")
    for k, r in res.items():
        print(f"- {k}: {r['exp_careful']:.1f} vs {r['exp_uniform']:.1f} "
              f"(careful keeps {r['exp_careful'] / r['exp_uniform']:.0%}); observed {r['canary_leaks']}")
    txt = {p.stem: p.read_text(errors="replace") for p in TRANSCRIPTS.glob("*.txt")}
    hits = sorted(int(k) for k, t in txt.items() if re.search(r"careful", t, re.I))
    print(f"\ntranscripts mentioning 'careful': {len(hits)}/{len(txt)}: {hits}")
    for k in hits[:40]:
        for m in re.finditer(r"[^\n.]{0,160}careful[^\n.]{0,200}", txt[str(k)], re.I):
            print(f"  seed {k}: …{m.group(0).strip()[:300]}…")
            break
    g = res["Gemini (OpenCode/MCP)"]["per_seed"]
    print("\nper seed (Gemini) for the loss seeds:", {s: g[s] for s in (1, 11, 15, 18, 26)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
