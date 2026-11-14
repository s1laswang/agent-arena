import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = ("reward", "harm", "tickets_done", "tickets_total")


def cache_dir():
    from agents import gemini

    return gemini.CACHE


def export(d, stem, keys, cache=None):
    from scripts import gemini_cache as gc

    cache = Path(cache or cache_dir())
    bad = [k for k in keys if (cache / (k + ".json")).is_file() and gc.SECRET.search((cache / (k + ".json")).read_text("utf8", "replace"))]
    if bad:
        raise SystemExit("refusing to pack, secret pattern in: " + ", ".join(bad))
    tmp = Path(tempfile.mkdtemp())
    for k in keys:
        if (cache / (k + ".json")).is_file():
            (tmp / (k + ".json")).write_bytes((cache / (k + ".json")).read_bytes())
    out = Path(d) / ("cache-" + stem.split("-", 1)[1] + ".tar.gz")
    gc.pack(str(out), tmp)
    return out


def rerun(row, cache, extra_env=None):
    out = tempfile.mkdtemp()
    env = {**os.environ, "GEMINI_API_KEY": "", "SLEEPER_OFFLINE": "1", "SLEEPER_CACHE_DIR": str(cache), "PYTHONPATH": str(ROOT), **(extra_env or {})}
    cmd = [sys.executable, "-m", "lab.frontier_rows", "--model", row["model"], "--day-start", str(row["seed"]), "--days", "1", "--trials", "1", "--trial-start", str(row["trial"]), "--seat", row["seat"], "--team", row["team"], "--sleeper", row["sleeper_mode"], "--budget-calls", "350", "--out", out]
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    hits = list(Path(out).glob("*/*/finance_ap-s*.json")) + list(Path(out).glob("*/*/%s-s*.json" % row["seat"]))
    if p.returncode or not hits:
        raise SystemExit("replay failed (cache miss = not replayable): " + (p.stderr or p.stdout)[-600:])
    return json.loads(hits[0].read_text())


def same(a, b):
    diff = [k for k in KEYS if a["scores"][k] != b["scores"][k]]
    if any(a["transcript"].get(k) != b["transcript"].get(k) for k in ("steps", "ledger", "messages")):
        diff.append("transcript")
    return diff


def replay(run):
    from scripts import gemini_cache as gc

    run = Path(run)
    row = json.loads(run.read_text())
    if row.get("invalid"):
        raise SystemExit("row is invalid, nothing to replay")
    tar = run.parent / ("cache-" + run.stem.split("-", 1)[1] + ".tar.gz")
    cache = Path(tempfile.mkdtemp())
    gc.unpack(str(tar), cache)
    new = rerun(row, cache)
    if new.get("invalid"):
        raise SystemExit("replay invalid: " + new["invalid"])
    diff = same(row, new)
    if diff:
        raise SystemExit("MISMATCH: " + ", ".join(diff))
    print("REPLAY OK reward=%s tickets=%s/%s calls_from_cache=%s %s" % (row["scores"]["reward"], row["scores"]["tickets_done"], row["scores"]["tickets_total"], new["cache_hits"], run))


def backfill(run, src_cache):
    run = Path(run)
    row = json.loads(run.read_text())
    used = tempfile.mktemp()
    new = rerun(row, src_cache, {"SLEEPER_USED_FILE": used})
    diff = same(row, new)
    if diff:
        raise SystemExit("backfill replay differs: " + ", ".join(diff))
    out = export(run.parent, run.stem, set(Path(used).read_text().split()), src_cache)
    print("packed", out)


if __name__ == "__main__":
    cmd, *a = sys.argv[1:]
    {"replay": replay, "backfill": backfill}[cmd](*a)
