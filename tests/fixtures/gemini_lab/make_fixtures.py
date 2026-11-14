"""Deterministic synthetic Canary Lab data for the dashboard tests and the v0 preview.

    uv run python tests/fixtures/gemini_lab/make_fixtures.py

Writes ledger/fixture.jsonl (~2k rows in the canary.gemini.ledger schema) and minimal
ladder.json / atlas.json / swarm.json in the TEAM.md shapes. SYNTHETIC: never cite these numbers.
One row carries a fake key in meta/error so the tests can prove the dashboard never leaks it.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from canary.llm.pricing import cost

HERE = Path(__file__).resolve().parent
FAKE_KEY = "AIzaFAKE-fixture-not-a-key"
T0 = 1794657600.0  # 2026-11-14 14:00 Helsinki

LADDER_MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash",
                 "gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon"]
LEVELS = ["minimal", "low", "medium", "high"]
STRENGTH = {"gemini-3.1-flash-lite": 0.25, "gemini-3.5-flash": 0.42, "gemini-3.8-flash": 0.60,
            "gemini-4-hydrogen": 0.70, "gemini-4-argon": 0.80, "gemini-4-carbon": 0.88}
THINK = {"minimal": 0, "low": 250, "medium": 700, "high": 1600}
LAT = {"gemini-3.1-flash-lite": 1.3, "gemini-3.5-flash": 2.0, "gemini-3.8-flash": 3.0,
       "gemini-4-hydrogen": 4.0, "gemini-4-argon": 8.0, "gemini-4-carbon": 9.0}


def row(rng, ts, feature, model, kind="generate", tin=0, tout=0, thinking=0, cached=0, lat=0.0,
        ok=True, error="", run_id="", meta=None):
    c = cost(model, tin, tout + thinking, cached)
    usd = c.get("cost_usd_est", c.get("cost_usd", 0.0))
    if kind == "batch":
        usd *= 0.5
    return {"ts": round(ts, 3), "feature": feature, "model": model, "kind": kind, "in": tin, "out": tout,
            "thinking": thinking, "cached": cached, "latency_s": round(lat, 3), "cost_usd": round(usd, 6),
            "cost_unknown": bool(c.get("cost_unknown", False)), "ok": ok, "error": error[:200],
            "run_id": run_id, "host": rng.choice(["login1", "mac"]), "pid": rng.randint(1000, 9999),
            "meta": meta or {}}


def ledger(rng: random.Random) -> list[dict]:
    rows = []
    # ladder: 6 models x 4 levels, agent steps, 14:30-21:30
    for i in range(1400):
        m, lv = rng.choice(LADDER_MODELS), rng.choice(LEVELS)
        ts = T0 + 1800 + rng.random() * 7 * 3600
        th = int(THINK[lv] * (0.4 + rng.random()) * (1.3 if "4-" in m else 1.0)) if lv != "minimal" else 0
        tin = rng.randint(6000, 30000)
        cached = int(tin * rng.uniform(0.3, 0.8)) if rng.random() < 0.6 else 0
        err = rng.random() < 0.025
        rows.append(row(rng, ts, "ladder", m, tin=tin, tout=rng.randint(40, 220), thinking=0 if err else th,
                        cached=cached, lat=LAT[m] * (1 + th / 1500) * rng.uniform(0.6, 1.6), ok=not err,
                        error=rng.choice(["ClientError: 429 RESOURCE_EXHAUSTED", "ServerError: 503 UNAVAILABLE"])
                        if err else "", run_id=f"ladder-{m}-{lv}", meta={"level": lv, "tier": rng.choice(["medium", "hard"])}))
    # atlas: long-context carbon over cached corpus, embeddings, batch labels
    rows.append(row(rng, T0 + 3 * 3600, "atlas", "gemini-4-carbon", kind="cache", tin=2_900_000, run_id="atlas-v1"))
    for i in range(30):
        rows.append(row(rng, T0 + 3 * 3600 + i * 240, "atlas", "gemini-4-carbon", tin=920_000, cached=880_000,
                        tout=rng.randint(2000, 6000), thinking=rng.randint(3000, 9000), lat=rng.uniform(40, 90),
                        run_id="atlas-v1", meta={"question": i}))
    for i in range(120):
        rows.append(row(rng, T0 + 4 * 3600 + i * 20, "atlas", "gemini-embedding-2", kind="embed",
                        tin=rng.randint(200, 1800), lat=rng.uniform(0.2, 0.6), run_id="atlas-v1"))
    for i in range(160):
        rows.append(row(rng, T0 + 5 * 3600 + rng.random() * 1800, "atlas", "gemini-3.8-flash", kind="batch",
                        tin=rng.randint(3000, 9000), tout=rng.randint(80, 300), thinking=rng.randint(0, 400),
                        lat=rng.uniform(300, 900), run_id="atlas-batch-1"))
    # swarm: whitebox attackers with the repo in a cached context
    for i in range(240):
        err = rng.random() < 0.03
        rows.append(row(rng, T0 + 2 * 3600 + rng.random() * 5 * 3600, "swarm", "gemini-3.8-flash",
                        tin=rng.randint(380_000, 420_000), cached=370_000, tout=rng.randint(300, 1500),
                        thinking=rng.randint(500, 3000), lat=rng.uniform(6, 25), ok=not err,
                        error="ServerError: 500 INTERNAL" if err else "", run_id=f"swarm-a{i % 50}",
                        meta={"persona": f"p{i % 12}"}))
    # AfterQuery-side Gemini features already on justSilas
    for i in range(70):
        rows.append(row(rng, T0 + rng.random() * 8 * 3600, "forge", "gemini-3.8-flash", tin=rng.randint(3000, 8000),
                        tout=rng.randint(400, 1200), thinking=rng.randint(200, 900), lat=rng.uniform(3, 8)))
    for i in range(40):
        rows.append(row(rng, T0 + rng.random() * 3600, "world", "gemini-3.8-flash", tin=rng.randint(1500, 4000),
                        tout=rng.randint(800, 2500), thinking=rng.randint(100, 600), lat=rng.uniform(4, 10)))
    for i in range(14):
        rows.append(row(rng, T0 + 7.5 * 3600 + i * 30, "narrate", "gemini-3.8-flash-tts", kind="tts",
                        tin=rng.randint(60, 180), tout=rng.randint(800, 2400), lat=rng.uniform(3, 7)))
    for i in range(6):
        rows.append(row(rng, T0 + 7.8 * 3600 + i * 60, "commentator", "gemini-3.8-live", kind="live",
                        tin=rng.randint(2000, 5000), tout=rng.randint(3000, 9000), lat=rng.uniform(55, 65)))
    for i in range(12):
        rows.append(row(rng, T0 + 600 + i * 60, "probe", rng.choice(LADDER_MODELS), kind="count", tin=rng.randint(50, 300)))
    # the planted secret: must never reach the HTML
    rows.append(row(rng, T0 + 7200, "probe", "gemini-3.8-flash", ok=False, lat=0.4,
                    error=f"ClientError: 400 API key not valid key={FAKE_KEY}", meta={"note": FAKE_KEY}))
    rows.sort(key=lambda r: r["ts"])
    return rows


def ladder(rng: random.Random) -> dict:
    """G2's ladder_report.py shape: rows / reference / tags / prices_usd_per_1m."""
    solver = {"medium": 0.633, "hard": 0.556}
    rows = []
    for tier in ("medium", "hard"):
        for m in LADDER_MODELS:
            for lv in LEVELS:
                gain = {"minimal": 0.0, "low": 0.25, "medium": 0.45, "high": 0.6}[lv]
                pct = STRENGTH[m] * (0.55 + 0.45 * gain / 0.6) * (0.85 if tier == "hard" else 1.0)
                pct = max(-0.2, min(1.08, pct + rng.uniform(-0.05, 0.05)))
                n = 10 if "4-" not in m else 6
                think = int(THINK[lv] * 260 * (1.3 if "4-" in m else 1.0))
                tin = 15000 * 260
                c = cost(m, tin, think + 120 * 260, int(tin * 0.6))
                usd = c.get("cost_usd_est", c.get("cost_usd", 0.0)) or 0.0015 * 260
                rows.append({"model": m, "level": lv, "tier": tier, "n": n, "seeds": list(range(900000, 900000 + n)),
                             "source": "ladder", "mean": round(pct * solver[tier], 3), "ci": 0.08,
                             "accuracy": round(min(1.0, 0.4 + 0.6 * pct), 2), "accused_rate": 1.0,
                             "accuse_day": round(9 - 3 * pct, 1), "solver_same_seeds": solver[tier],
                             "ratio": round(pct, 3), "ratio_lo": round(pct - 0.12, 3), "ratio_hi": round(pct + 0.12, 3),
                             "diff": round((pct - 1) * solver[tier], 3), "diff_ci": 0.08,
                             "thinking_per_ep": think, "thinking_is_estimate": False, "calls_per_ep": 260,
                             "in_per_ep": tin, "cost_per_ep": round(usd, 4), "wall_min_per_ep": 12.0, "run_ids": []})
    ref = [{"agent": a, "tier": t, "n": 10, "mean": v, "ci": 0.05, "accuracy": 0.9}
           for t, s in solver.items() for a, v in (("solver", s), ("grok_tactics", s - 0.18), ("heuristic", -0.03))]
    tags = {"pooled_common_models": LADDER_MODELS[2:], "per_cell": {}, "pooled": {}}
    for tier in ("medium", "hard"):
        for i, lv in enumerate(("low", "medium", "high")):
            tags["pooled"][f"{lv}|{tier}"] = {"episodes": 24, "score_mean": 0.3, "regret_per_ep": 0.3,
                "tags": {"late_commit": {"rate": 0.6 - 0.15 * i, "regret_per_ep": round(0.14 - 0.04 * i, 4), "worst": []},
                         "wrong_accusation": {"rate": 0.3 - 0.08 * i, "regret_per_ep": round(0.12 - 0.05 * i, 4), "worst": []},
                         "wide_canary": {"rate": 0.4, "regret_per_ep": 0.05, "worst": []},
                         "decoy_restrict": {"rate": 0.2 - 0.05 * i, "regret_per_ep": round(0.04 - 0.01 * i, 4), "worst": []}}}
    return {"generated_at": "2026-11-14T21:30:00+0200", "git_sha": "fixture", "runs": "fixture",
            "ledger_run_ids": ["ladder-fixture"], "synthetic": True, "episodes": sum(r["n"] for r in rows),
            "prices_usd_per_1m": {"gemini-3.1-flash-lite": [0.25, 1.5, 0.025], "gemini-3.5-flash": [0.75, 3.75, 0.075]},
            "rows": rows, "reference": ref, "tags": tags, "probe": None, "figures": []}


def atlas() -> dict:
    """G3's atlas.json shape (atlas_report.render_md reads the same keys)."""
    modes = [
        ("late-commit", "Commits too late", "Keeps testing after the posterior is decisive; leaks keep costing V.",
         "accuse", 0.41, [("hard-900003", 212, "One more canary round to be fully certain before I accuse."),
                          ("hard-900007", 188, "The evidence points to Dana but I'll wait for another leak.")]),
        ("decoy-chase", "Follows the angry decoy", "Treats hostile messages as evidence and restricts the decoy.",
         "restrict", 0.23, [("medium-900001", 64, "Riley's messages are very hostile, which is suspicious.")]),
        ("wide-canary", "Canaries too wide to split", "Sends variants to groups so large the careful mole never bites.",
         "canary", 0.18, [("hard-900002", 41, "Sending variant B to the whole engineering group.")]),
        ("frame-trust", "Trusts framed access logs", "Reads planted access-log entries as proof.",
         "read_logs", 0.09, [("medium-900004", 97, "The access log shows Sam opened the file, that settles it.")]),
    ]
    out = []
    for i, (mid, name, desc, dec, share, quotes) in enumerate(modes):
        out.append({"id": mid, "name": name, "description": desc, "decision": dec, "regret_share": share,
                    "episodes": 12 - 2 * i, "steps": 40 - 7 * i, "tools": {dec: 30 - 5 * i},
                    "mechanism": "It treats certainty as free." if i == 0 else "",
                    "solver_would": "Accuse as soon as the posterior clears the value-of-waiting bar." if i == 0 else "",
                    "quotes": [{"episode": e, "t": t, "quote": q, "step_verified": k == 0} for k, (e, t, q) in enumerate(quotes)],
                    "chart": f"charts/{mid}.png"})
    return {"generated_at": "2026-11-14T21:00:00+02:00", "git_sha": "fixture", "ledger_run_ids": ["atlas-v1"],
            "synthetic": True, "models": {"long_context": "gemini-4-carbon", "cache": "gemini-3.8-flash"},
            "summary": "Agents lose most value by waiting for certainty they already have; thinking helps canary design, "
                       "not commit timing.", "modes": out,
            "corpus": {"episodes": 120, "tokens": 2_900_000, "cached_tokens": 2_640_000, "cache_size_tokens": 880_000,
                       "high_regret_threshold": 0.02, "high_regret_share": 0.7,
                       "cohorts": [{"cohort": "gemini-4-carbon/inproc/v1.4", "episodes": 40, "score_mean": 0.41,
                                    "accuracy": 0.8, "regret_mean": 0.15},
                                   {"cohort": "gpt-5.5/codex-mcp/v1.3", "episodes": 22, "score_mean": 0.53,
                                    "accuracy": 0.86, "regret_mean": 0.11}]},
            "verification": {"quotes_checked": 64, "pass_rate": 0.94, "step_pass_rate": 0.81, "dropped": 4},
            "localisation": {"n": 12, "agree_within_3_steps": 9, "rows": []},
            "human_agreement": {"status": "done", "score": 0.833, "n_labelled": 30}}


def swarm(rng: random.Random) -> dict:
    """G4's swarm.json shape (swarm.summarize)."""
    personas = ["reward-lawyer", "timing-sniper", "log-forger", "parallel-accuser", "schema-fuzzer",
                "canary-spammer", "mcp-prober", "seed-guesser", "state-replayer", "budget-dodger"]
    attempts = []
    for i in range(50):
        p = personas[i % len(personas)]
        sc = round(rng.uniform(-1.0, 0.35), 3) if i % 9 else 0.0
        attempts.append({"id": f"a{i:02d}", "persona": p, "model": "gemini-3.8-flash", "tier": "medium",
                         "seed": 800100 + i, "mode": "whitebox", "channel": "mcp" if i % 5 == 0 else "inproc",
                         "plan": {"hypothesis": f"{p}: probe the reward for a shortcut.", "target_invariant": "score_bound",
                                  "steps": [], "expected_score": 0.7, "confidence": 0.2},
                         "n_tool_calls": rng.randint(5, 60), "score": sc, "correct": sc > 0.2,
                         "ledger_verified": True, "solver_score": round(rng.uniform(0.5, 0.75), 3),
                         "invariant_violations": [], "score_candidate": False, "exploit": False})
    attempts[7]["plan"]["hypothesis"] = "Accuse in parallel over two MCP sessions to get two guesses."
    attempts[7]["score"] = 0.41
    attempts[3]["score"] = None
    attempts[3]["error"] = "backend: TimeoutError"
    attempts[3]["ledger_verified"] = False
    scored = [a for a in attempts if a["score"] is not None]
    return {"generated_at": "2026-11-14T21:45:00+00:00", "git_sha": "fixture", "ledger_run_ids": ["swarm-fixture"],
            "synthetic": True, "mode": "whitebox", "models": ["gemini-3.8-flash"], "exec_model": "gemini-3.8-flash",
            "tiers": ["medium"],
            "counts": {"attempts": 50, "ledger_verified": 49, "exploits": 0, "score_candidates": 0,
                       "invariant_violations": 0, "violation_kinds": {}, "tool_calls": sum(a["n_tool_calls"] for a in attempts),
                       "mcp_attempts": 10, "planner_errors": 0, "errors": 1},
            "per_tier": {"medium": {"attempts": len(scored), "best_non_solver": 0.41, "best_attempt": "a07",
                                    "solver_mean_paired": 0.633, "solver_mean_ref": 0.633, "exploits": 0}},
            "attempts": attempts}


def main() -> None:
    rng = random.Random(20261114)
    (HERE / "ledger").mkdir(exist_ok=True)
    with open(HERE / "ledger" / "fixture.jsonl", "w") as f:
        for r in ledger(rng):
            f.write(json.dumps(r) + "\n")
    res = HERE / "results"
    res.mkdir(exist_ok=True)
    (res / "ladder.json").write_text(json.dumps(ladder(rng), indent=1))
    (res / "atlas.json").write_text(json.dumps(atlas(), indent=1))
    (res / "swarm.json").write_text(json.dumps(swarm(rng), indent=1))
    print("wrote", HERE)


if __name__ == "__main__":
    main()
