"""Spot check: gemini-4-carbon (in-process LLMPolicy, full context) on the RL mole (hard_rl) vs the default mole
(hard), SAME held-out seeds, plus the solver on both. Transcripts + results -> data/runs/rl_mole_gemini/.
    uv run --extra llm python scripts/rl_mole_gemini_spot.py --seeds 200000-200005 --workers 3
"""
import argparse, json, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

MODEL = "gemini:gemini-4-carbon"
OUT = Path("data/runs/rl_mole_gemini")


def one(task):
    from dotenv import load_dotenv
    load_dotenv(".env")
    from canary.agents.llm_policy import LLMPolicy
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy
    tier, seed, agent = task
    t = time.time()
    env = Env(tier, seed)
    pol = SolverPolicy("hard") if agent == "solver" else LLMPolicy(MODEL)
    try:
        r = run_episode(env, pol)
        row = {"tier": tier, "seed": seed, "agent": agent if agent == "solver" else MODEL, "score": r.score,
               "correct": r.correct, "n_calls": len(env.history), "sec": round(time.time() - t, 1),
               "usage": getattr(pol, "usage", None), "valid": True}
    except Exception as e:  # infra failure: recorded, not hidden
        row = {"tier": tier, "seed": seed, "agent": agent, "valid": False, "error": repr(e)[:500]}
    if agent != "solver":
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{tier}-{seed}.json").write_text(json.dumps({**row, "steps": [
            {"tool": s.tool, "args": s.args, "result": s.result, "day": s.day} for s in env.history]}, default=str))
    return row


def main():
    from canary.eval import parse_seeds
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="200000-200005")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    tasks = [(t, s, ag) for s in parse_seeds(a.seeds) for t in ("hard_rl", "hard") for ag in ("gemini", "solver")]
    with ProcessPoolExecutor(a.workers) as ex:
        rows = list(ex.map(one, tasks))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    for t in ("hard_rl", "hard"):
        for ag in ("solver", MODEL):
            rs = [r for r in rows if r["tier"] == t and r.get("agent") == ag and r["valid"]]
            if rs:
                print(t, ag, "n", len(rs), "score", round(sum(r["score"] for r in rs) / len(rs), 3),
                      "acc", sum(r["correct"] for r in rs) / len(rs))
    print("invalid:", [(r["tier"], r["seed"], r["error"][:80]) for r in rows if not r["valid"]])


if __name__ == "__main__":
    main()
