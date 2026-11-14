"""Run J1 calibration on the Mac with <=3 processes (same CSV format as the Slurm array).

  uv run --python 3.12 --extra dev python fr8/local_j1.py [--cells 0-305] [--seeds 500] [--procs 3]
Outputs data/fr8/j1/parts/cellNNNN.csv; then: python fr8/j1_summarize.py data/fr8/j1
Cells already complete are skipped (resumable). Gate: run only once contract v0.3 + solver v1 are merged.
"""
import argparse, subprocess, sys
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def one(args):
    cell, seeds, out, agents = args
    if (Path(out) / "parts" / f"cell{cell:04d}.done").exists():
        return cell, 0
    cmd = [sys.executable, str(ROOT / "fr8/j1_grid.py"), "--task", str(cell), "--seeds", str(seeds), "--out", out]
    if agents:
        cmd += ["--agents", agents]
    rc = subprocess.call(cmd, cwd=ROOT, env={"OMP_NUM_THREADS": "1", **__import__("os").environ})
    if rc == 0:
        (Path(out) / "parts" / f"cell{cell:04d}.done").touch()
    return cell, rc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="0-305")
    ap.add_argument("--seeds", type=int, default=500)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--agents", default="")
    ap.add_argument("--out", default=str(ROOT / "data/fr8/j1"))
    a = ap.parse_args()
    assert a.procs <= 3, "Mac budget: at most 3 processes"
    lo, _, hi = a.cells.partition("-")
    cells = range(int(lo), int(hi or lo) + 1)
    with Pool(a.procs) as p:
        for cell, rc in p.imap_unordered(one, [(c, a.seeds, a.out, a.agents) for c in cells]):
            print(f"cell {cell} rc={rc}", flush=True)
