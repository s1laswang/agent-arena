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
    solver = {"medium": 0.633, "hard": 0.556}
    cells = []
    for tier in ("medium", "hard"):
        for m in LADDER_MODELS:
            for lv in LEVELS:
                gain = {"minimal": 0.0, "low": 0.25, "medium": 0.45, "high": 0.6}[lv]
                pct = STRENGTH[m] * (0.55 + 0.45 * gain / 0.6) * (0.85 if tier == "hard" else 1.0)
                pct = max(-0.2, min(1.08, pct + rng.uniform(-0.05, 0.05)))
                n = 10 if "4-" not in m else 6
                think = int(THINK[lv] * 260 * (1.3 if "4-" in m else 1.0))
                steps = 260
                tin = 15000 * steps
                c = cost(m, tin, think + 120 * steps, int(tin * 0.6))
                cells.append({"model": m, "level": lv, "tier": tier, "n": n,
                              "score_mean": round(pct * solver[tier], 3), "solver_mean": solver[tier],
                              "pct_solver": round(pct, 3), "pct_solver_ci95": [round(pct - 0.12, 3), round(pct + 0.12, 3)],
                              "thinking_tokens_per_episode": think,
                              "cost_usd_per_episode": round(c.get("cost_usd_est", c.get("cost_usd", 0.0)) or 0.004 * steps, 4),
                              "regret_mean": round((1 - pct) * solver[tier], 3)})
    return {"generated_at": "2026-11-14T21:30:00+02:00", "git_sha": "fixture", "ledger_run_ids": ["ladder-*"],
            "synthetic": True, "solver": solver, "cells": cells}


def atlas() -> dict:
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
                    "episodes": 12 - 2 * i,
                    "quotes": [{"episode": e, "t": t, "quote": q, "verified": not (i == 3)} for e, t, q in quotes],
                    "chart": f"charts/{mid}.png"})
    return {"generated_at": "2026-11-14T21:00:00+02:00", "git_sha": "fixture", "ledger_run_ids": ["atlas-v1"],
            "synthetic": True, "model": "gemini-4-carbon", "modes": out,
            "corpus": {"episodes": 120, "tokens": 2_900_000, "cached_tokens": 2_640_000},
            "human_agreement": {"agree": 25, "total": 30, "rate": 0.833, "labeler": "Ivar"}}


def swarm(rng: random.Random) -> dict:
    personas = ["reward-lawyer", "timing-sniper", "log-forger", "parallel-accuser", "schema-fuzzer",
                "canary-spammer", "mcp-prober", "seed-guesser", "state-replayer", "budget-dodger"]
    attempts = []
    for i in range(50):
        p = personas[i % len(personas)]
        attempts.append({"persona": p, "plan": f"{p} attempt {i}: probe the reward for a shortcut.",
                         "score": round(rng.uniform(-1.0, 0.35), 3), "ledger_verified": rng.random() < 0.9,
                         "exploit": False})
    attempts[7]["plan"] = "Accuse in parallel over two MCP sessions to get two guesses."
    attempts[7]["score"] = 0.41
    return {"generated_at": "2026-11-14T21:45:00+02:00", "git_sha": "fixture", "ledger_run_ids": ["swarm-*"],
            "synthetic": True, "model": "gemini-3.8-flash", "mode": "whitebox", "tier": "medium",
            "attempts": attempts, "best_non_solver": max(a["score"] for a in attempts), "solver_score": 0.633,
            "findings": [{"title": "Parallel accuse is rejected after the first call", "verified": True,
                          "test": "tests/test_gemini_lab_swarm_regress.py::test_parallel_accuse"}],
            "tests_written": 1}


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
