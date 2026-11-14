"""Assemble scripts/budget_runner.py staging dirs (one episode per dir) into committed run dirs.

    python scripts/merge_staging.py --staging data/runs/staging-v1.3 --root data/runs/committed/v1.3 [--planned 0-9]

staging/codex/<tier>/<seed>/  -> <root>/codex-gpt-5.5-full/<tier>/
staging/inproc/<tier>/<seed>/ -> <root>/gpt-5.5-full/<tier>/
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

TARGET = {"codex": "codex-gpt-5.5-full", "inproc": "gpt-5.5-full"}
PRICING = ("gpt-5.5 list prices per 1M tokens: input $5.00, cached input $0.50, output $30.00 (<272K context), "
           "verified on developers.openai.com/api/docs/pricing on 2026-11-14. cost_usd_est bills cached input at "
           "$0.50; the upper bound bills all input at $5.00.")


def _current_tiers_version() -> str:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from canary.rules import TIERS_VERSION
    return TIERS_VERSION


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", default="data/runs/staging-v1.3")
    ap.add_argument("--root", default="data/runs/committed/v1.3")
    ap.add_argument("--planned", default="0-9", help="the approved plan's seeds; others are budget extensions")
    ap.add_argument("--extension", default=None, help="extension seed range attempted as budget allowed, e.g. 10-19")
    ap.add_argument("--tiers-version", default=_current_tiers_version(), help="rules.TIERS_VERSION the runs were played under")
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.planned.split("-"))
    planned = list(range(lo, hi + 1))
    staging, root = Path(a.staging), Path(a.root)
    for harness, target in TARGET.items():
        for tier in ("medium", "hard"):
            src = staging / harness / tier
            if not src.exists():
                continue
            eps, metas = [], []
            for d in sorted((p for p in src.iterdir() if p.is_dir()), key=lambda p: int(p.name)):
                f = d / "episodes.jsonl"
                if not f.exists() or not f.read_text().strip():
                    continue
                lines = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
                eps.append(lines[-1])
                metas.append(json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {})
            if not eps:
                continue
            out = root / target / tier
            (out / "transcripts").mkdir(parents=True, exist_ok=True)
            for e in eps:
                for t in (staging / harness / tier / str(e["seed"]) / "transcripts").glob(f"{e['seed']}.*"):
                    if t.suffix != ".log":
                        shutil.copy2(t, out / "transcripts" / t.name)
            (out / "episodes.jsonl").write_text("".join(json.dumps(e, default=str) + "\n" for e in eps))
            seeds = [e["seed"] for e in eps]
            usage = {"in": 0, "cached_in": 0, "out": 0, "cost_usd_est": 0.0, "cost_usd_upper": 0.0}
            for e in eps:
                u = (e.get("meta") or {}).get("usage") or {}
                usage["in"] += u.get("in", 0) or 0
                usage["cached_in"] += u.get("cached_in", 0) or 0
                usage["out"] += u.get("out", 0) or 0
                usage["cost_usd_est"] += u.get("cost_usd_est", u.get("cost_usd", 0)) or 0
                usage["cost_usd_upper"] += u.get("cost_usd_upper", u.get("cost_usd", 0)) or 0
            usage = {k: round(v, 4) if isinstance(v, float) else v for k, v in usage.items()}
            m0 = metas[0]
            shas = sorted({m.get("git_sha") for m in metas if m.get("git_sha")})
            missing = [s for s in planned if s not in seeds]
            ext = []
            if a.extension:
                elo, ehi = (int(x) for x in a.extension.split("-"))
                ext = list(range(elo, ehi + 1))
            meta = {k: m0.get(k) for k in ("agent", "model", "provider", "harness", "steps_source", "context",
                                           "reasoning_effort", "reasoning_effort_source", "api") if m0.get(k) is not None}
            meta.update({"tier": tier, "tiers_version": a.tiers_version, "seeds": seeds, "planned_seeds": planned,
                         "status": ("complete" if not missing else f"INCOMPLETE: seeds {missing} not run (budget stop)")
                         + (f"; extension seeds {ext[0]}-{ext[-1]} as budget allowed: ran {[s for s in seeds if s in ext]}"
                            if ext else ""),
                         "git_sha": shas[0] if shas else None, "git_shas": shas, "smoke": False, "hint": None,
                         "usage": usage, "pricing": PRICING,
                         "provenance": "scripts/budget_runner.py (one episode per process, budget-guarded), "
                                       "merged by scripts/merge_staging.py",
                         "invalid_episodes": [e["seed"] for e in eps if (e.get("meta") or {}).get("valid") is False]})
            (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n")
            print(f"{out}: n={len(eps)} seeds={seeds} est=${usage['cost_usd_est']:.2f} upper=${usage['cost_usd_upper']:.2f}"
                  f" {meta['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
