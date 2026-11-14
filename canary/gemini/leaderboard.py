"""Import the v1.4-hard leaderboard for the dashboard, from committed files only.

    python -m canary.gemini.leaderboard [--ref origin/justSilas] [--out results/gemini/leaderboard_v14_hard.json]

Source: `results/leaderboard_v14_hard.json` on --ref (written by the S7 training session as rounds finish: Qwen2.5-7B
base -> SFT -> expert iteration, next to gemini-4-carbon and the solver). It is copied verbatim under "source_json" with
the commit that last touched it, so the dashboard never re-types or relabels a value.

If that file is not committed yet, only the Gemini and solver rows are written, parsed from `docs/reports/gap.md` on the
same ref (v1.4 headline table, judges' harness row, hard), again with the commit SHA. Nothing is ever typed by hand.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LB_PATH = "results/leaderboard_v14_hard.json"
GAP_PATH = "docs/reports/gap.md"


def _git(*a: str) -> str | None:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _last_commit(ref: str, path: str) -> str | None:
    out = _git("log", "-1", "--format=%H", ref, "--", path)
    return out.strip() or None if out else None


def _ci(s: str) -> list[float] | None:
    m = re.search(r"\[(-?[\d.]+)%?,\s*(-?[\d.]+)%?\]", s)
    return [float(m.group(1)) / 100, float(m.group(2)) / 100] if m else None


def parse_gap(md: str) -> list[dict]:
    """Gemini + solver rows on v1.4 hard from gap.md's v1.4 headline (the judges'-harness row)."""
    sec = md.split("## v1.4 headline", 1)[1].split("\n## ", 1)[0] if "## v1.4 headline" in md else ""
    rows = []
    model = re.search(r"^(gemini-[\w.-]+), rules v1\.4", sec, re.M)
    for line in sec.splitlines():
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and "judges" in cells[0] and cells[1].strip("*") == "hard":
            pct = re.match(r"(-?[\d.]+)%", cells[3].strip("*"))
            lpct = re.match(r"(-?[\d.]+)%", cells[4].strip("*"))
            rows.append({"name": model.group(1) if model else "gemini", "stage": "frontier",
                         "harness": cells[0].replace("*", ""), "n": int(cells[2]),
                         "pct_solver": float(pct.group(1)) / 100 if pct else None, "pct_solver_ci": _ci(cells[3]),
                         "luck_adjusted_pct_solver": float(lpct.group(1)) / 100 if lpct else None,
                         "luck_adjusted_pct_solver_ci": _ci(cells[4]), "compute": None})
    sol = re.search(r"solver means: hard ([\d.]+)", sec)
    n = re.search(r"paired on all (\d+) seeds", sec)
    if sol:
        rows.append({"name": "reference solver", "stage": "solver", "harness": None, "n": int(n.group(1)) if n else None,
                     "score": float(sol.group(1)), "pct_solver": 1.0, "compute": None})
    return rows


def build(ref: str) -> dict:
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    raw = _git("show", f"{ref}:{LB_PATH}")
    if raw:
        return {"generated_at": now, "kind": "leaderboard", "ref": ref, "source": LB_PATH,
                "source_sha": _last_commit(ref, LB_PATH), "source_json": json.loads(raw)}
    gap = _git("show", f"{ref}:{GAP_PATH}") or ""
    return {"generated_at": now, "kind": "fallback_gap", "ref": ref, "source": GAP_PATH,
            "source_sha": _last_commit(ref, GAP_PATH),
            "note": f"{LB_PATH} not committed on {ref} yet: Gemini and solver rows only, from {GAP_PATH}.",
            "rows": parse_gap(gap)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default="origin/justSilas")
    ap.add_argument("--out", default=str(ROOT / "results" / "gemini" / "leaderboard_v14_hard.json"))
    a = ap.parse_args(argv)
    d = build(a.ref)
    Path(a.out).write_text(json.dumps(d, indent=1) + "\n")
    print(f"wrote {a.out}: {d['kind']} from {d['source']} @ {str(d['source_sha'])[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
