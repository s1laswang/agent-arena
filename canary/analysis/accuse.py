"""Per-seed accusation audit: when did the agent accuse, and was it justified?

For each episode: accuse day, accused, correct, score, and the solver's posterior at the moment of
accusation (p_accused = P(accused is mole | everything the agent had seen), p_top = max posterior).
"lucky" = correct with p_accused < 0.6; "justified" = p_accused >= 0.6.

    python -m canary.analysis.accuse --runs data/runs_v1 [--agent-prefix openai:] [--out x.md]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from canary.analysis.tags import load, to_result
from canary.rules import TIERS
from canary.solver.policy import SolverPolicy


def audit_episode(ep) -> dict:
    sp = SolverPolicy(TIERS[ep.tier])
    row = dict(tier=ep.tier, seed=ep.seed, agent=ep.agent, accused=ep.accused, correct=ep.correct,
               score=ep.score, day=ep.final_day, end=ep.end_reason, p_accused=None, p_top=None)
    for i, st in enumerate(ep.steps):
        if st.tool == "accuse":
            for prev in ep.steps[sp.seen:i]:
                sp._ingest(prev)
            sp.seen = i
            post = sp.belief() if sp.obs.employees else {}
            row["day"] = st.day
            row["p_accused"] = round(post.get(st.args.get("employee"), 0.0), 3) if post else None
            row["p_top"] = round(max(post.values()), 3) if post else None
            break
    p = row["p_accused"]
    row["verdict"] = ("none" if p is None else "justified" if p >= 0.6
                      else "lucky" if row["correct"] else "premature-wrong")
    return row


def audit(eps: list[dict], prefix: str = "") -> list[dict]:
    return [audit_episode(to_result(e)) for e in eps if e["agent"].startswith(prefix)]


def to_md(rows: list[dict]) -> str:
    out = ["| tier | agent | seed | day | accused | correct | score | P(accused) | P(top) | verdict |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["tier"], r["agent"], r["seed"])):
        out.append(f"| {r['tier']} | {r['agent']} | {r['seed']} | {r['day']} | {r['accused']} | {r['correct']} | "
                   f"{r['score']:.2f} | {r['p_accused']} | {r['p_top']} | {r['verdict']} |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="data/runs")
    ap.add_argument("--agent-prefix", default="")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    md = to_md(audit(load(a.runs), a.agent_prefix))
    print(md)
    if a.out:
        Path(a.out).write_text(md + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
