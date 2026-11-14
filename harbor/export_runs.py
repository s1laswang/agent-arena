#!/usr/bin/env python3
"""Copy Harbor trial trajectories into pinbox's recorded-runs layout (stdlib only).

    python harbor/export_runs.py harbor/jobs --out runs/recorded/harbor
    python -m pinbox eval --include-recorded runs/recorded/harbor     # re-grades every run by replay

Each trial becomes <out>/<agent>/<episode_id>-r<k>/ with trajectory.jsonl and meta.json
(family, seed, difficulty, payload mode, agent, repeat, and the reward Harbor gave).
Replaying them rebuilds each world from its seed, sends the same tool calls again and grades
the result, so anyone can check a Harbor score offline without Docker or API keys.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from summarize import find_jobs  # noqa: E402


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in text)[:80]


def agent_of(cfg: dict) -> tuple[str, str]:
    """(agent label, kind) from a trial's config."""
    agent = (cfg or {}).get("agent") or {}
    name = agent.get("name") or agent.get("import_path") or "unknown"
    env = agent.get("env") or {}
    if name == "oracle":
        return f"harbor-oracle:{env.get('PINBOX_SOLUTION') or 'reference'}", "scripted"
    if name == "nop":
        return "harbor-nop", "scripted"
    model = agent.get("model_name")
    return (f"{name} ({model})" if model else name), "llm"


def export(job_paths: list[str], out: Path, prefix: str = "") -> list[dict]:
    done = []
    counts: dict = {}
    for job in find_jobs(job_paths, prefix):
        for tdir in sorted(c for c in job.iterdir() if c.is_dir()):
            res = _load(tdir / "result.json")
            evid = tdir / "artifacts" / "srv" / "pinbox" / "out"   # separate-verifier builds
            if not (evid / "trajectory.jsonl").is_file():
                evid = tdir / "verifier"                          # shared-verifier builds
            if not isinstance(res, dict) or not (evid / "trajectory.jsonl").is_file():
                continue
            state = _load(evid / "final_state.json") or {}
            meta = dict(state.get("meta") or {})
            grade = _load(evid / "grade.json") or {}
            for key in ("family", "seed", "difficulty", "episode_id"):
                meta.setdefault(key, grade.get(key))
            if not meta.get("episode_id"):
                continue
            label, kind = agent_of(res.get("config") or {})
            key = (label, meta["episode_id"])
            repeat = counts.get(key, 0)
            counts[key] = repeat + 1
            rewards = (res.get("verifier_result") or {}).get("rewards") or {}
            meta.update({"agent": label, "kind": kind, "repeat": repeat, "reward": rewards.get("reward"),
                         "source": "harbor", "harbor_job": job.name, "harbor_trial": res.get("trial_name")})
            dest = out / _slug(label) / f"{meta['episode_id']}-r{repeat}"
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(evid / "trajectory.jsonl", dest / "trajectory.jsonl")
            (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            done.append({"agent": label, "episode_id": meta["episode_id"], "repeat": repeat,
                         "reward": meta["reward"], "path": str(dest)})
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Export Harbor trial trajectories as pinbox recorded runs")
    p.add_argument("paths", nargs="+", help="Harbor job folders, or a jobs folder holding them")
    p.add_argument("--out", default="runs/recorded/harbor", help="output folder (default runs/recorded/harbor)")
    p.add_argument("--prefix", default="", help="only jobs whose folder name starts with this")
    a = p.parse_args(argv)
    done = export(a.paths, Path(a.out), a.prefix)
    by_agent: dict = {}
    for d in done:
        by_agent.setdefault(d["agent"], []).append(d)
    for agent, runs in sorted(by_agent.items()):
        rewards = [r["reward"] for r in runs if isinstance(r["reward"], (int, float))]
        mean = sum(rewards) / len(rewards) if rewards else 0.0
        print(f"{agent:40} {len(runs):4} run(s)  mean Harbor reward {mean:.3f}")
    print(f"exported {len(done)} run(s) to {a.out}")
    print(f"re-grade them offline: python -m pinbox eval --include-recorded {a.out}")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
