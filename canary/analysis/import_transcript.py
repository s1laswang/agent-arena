"""Import an external agent's MCP tool-call transcript as an EpisodeResult by REPLAYING it.

The Env is deterministic in (tier, seed, action sequence), so replaying the recorded calls
reproduces the episode exactly; we then assert the replayed score matches the reported one.

    python -m canary.analysis.import_transcript --agent grok --src DIR --out data/runs/committed/grok
    (DIR holds <tier>-<seed>.jsonl with one {"tool","args",...} per line)
"""
from __future__ import annotations

import argparse
import re
import dataclasses
import json
import os
from pathlib import Path

from canary.env import Env
from canary.types import EpisodeResult, Step

JUDGE_LO, JUDGE_HI = 900_000, 900_030


def parse_report(md: str) -> dict[tuple[str, int], dict]:
    """Rows of a markdown table: | tier | seed | score | accused | correct | final day | ..."""
    out = {}
    for line in md.splitlines():
        m = re.match(r"\|\s*(easy|medium|hard)\s*\|\s*(\d+)\s*\|\s*(-?[\d.]+)\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*(\d+)\s*\|", line)
        if m:
            acc = m.group(4).strip()
            out[(m.group(1), int(m.group(2)))] = dict(
                score=float(m.group(3)), accused=acc if re.fullmatch(r"e\d+", acc) else None,
                correct=m.group(5).strip().lower() == "yes", final_day=int(m.group(6)))
    return out


def from_report(tier: str, seed: int, calls: list[dict], rep: dict, agent: str) -> EpisodeResult:
    """Judge seeds use a server-side secret salt, so they cannot be replayed: take the outcome from
    the agent's ledger-backed report and the steps from its transcript."""
    day, steps = 1, []
    for i, c in enumerate(calls):
        try:
            res = json.loads(c["result"]) if isinstance(c.get("result"), str) else (c.get("result") or {})
        except json.JSONDecodeError:
            res = {"raw": c.get("result")}
        steps.append(Step(t=i, day=day, tool=c["tool"], args=c.get("args") or {}, result=res))
        if c["tool"] == "advance_day":
            day += 1
    end = "accused" if rep["accused"] else "horizon"
    return EpisodeResult(tier=tier, seed=seed, agent=agent, steps=steps, score=rep["score"],
                         accused=rep["accused"], correct=rep["correct"], final_day=rep["final_day"],
                         end_reason=end, meta={"source": "external report (ledger) + transcript; NOT replay-verified"})


def replay(tier: str, seed: int, calls: list[dict], agent: str):
    env = Env(tier, seed)
    for c in calls:
        if env.done:
            break
        env.call(c["tool"], c.get("args") or {})
    return env.result(agent)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", help="markdown report with the per-seed ledger table (needed for judge seeds)")
    a = ap.parse_args(argv)
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    out = Path(a.out)
    rows = {}
    for f in sorted(Path(a.src).glob("*-*.jsonl")):
        tier, seed = f.stem.split("-")
        calls = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        calls = [c for c in calls if c.get("tool") and c["tool"] != "init"]
        if JUDGE_LO <= int(seed) < JUDGE_HI:
            rep = parse_report(Path(a.report).read_text()) if a.report else {}
            if (tier, int(seed)) not in rep:
                raise SystemExit(f"{f.name}: judge seed needs --report with a row for it")
            res = from_report(tier, int(seed), calls, rep[(tier, int(seed))], a.agent)
        else:
            res = replay(tier, int(seed), calls, a.agent)
            res.meta.update(source="replayed_external_transcript")
        res.meta.update(transcript=f.name, n_calls=len(calls))
        rows.setdefault(tier, []).append(res)
        print(f"{tier} {seed}: score={res.score:.3f} correct={res.correct} accused={res.accused} day={res.final_day} end={res.end_reason}")
    for tier, rs in rows.items():
        d = out / tier
        d.mkdir(parents=True, exist_ok=True)
        (d / "episodes.jsonl").write_text("".join(json.dumps(dataclasses.asdict(r)) + "\n" for r in rs))
        (d / "meta.json").write_text(json.dumps({"agent": a.agent, "tier": tier, "seeds": [r.seed for r in rs],
                                                 "source": "replayed external MCP transcripts", "src": str(a.src)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
