import argparse
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAFE = {"end_turn", "search_docs", "my_tickets", "verify_bank_details"}


def shape(v):
    if isinstance(v, dict):
        return {k: shape(x) for k, x in sorted(v.items())}
    if isinstance(v, list):
        return [shape(x) for x in v]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return "<N>"
    if re.fullmatch(r"[A-Z]{2}\d{2}\w{10,30}", v):
        return "<IBAN>"
    if v.startswith("external:"):
        return "external:*"
    if re.fullmatch(r"[A-Za-z]{1,6}[-_]?\w{0,10}\d+", v):
        return "<ID>"
    return "<TEXT>" if len(v) > 12 else v


def risky(name):
    return name not in SAFE and not name.startswith(("read_", "list_"))


def mine(cache, model, commit, label=None):
    seen = {}
    for f in sorted(glob.glob(str(Path(cache) / "*.json"))):
        if f.endswith("usage.json"):
            continue
        for c in json.load(open(f)).get("tool_calls", []):
            if not risky(c["name"]):
                continue
            key = json.dumps([c["name"], shape(c.get("args") or {})], sort_keys=True)
            seen.setdefault(key, {"tool": c["name"], "args": c.get("args") or {}, "pattern": key, "model": model, "commit": commit, "day": label or "cache", "count": 0})["count"] += 1
    return list(seen.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache" / "gemini"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--label", default=None)
    a = ap.parse_args()
    usage = Path(a.cache) / "usage.jsonl"
    models = {json.loads(l)["model"] for l in usage.read_text().splitlines() if l} if usage.is_file() else set()
    model = a.model or (models.pop() if len(models) == 1 else "unknown")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    rows = mine(a.cache, model, commit, a.label)
    out = ROOT / "redteam" / "corpus" / f"real_{model}.jsonl"
    old = {json.loads(l)["pattern"] for l in out.read_text().splitlines() if l} if out.is_file() else set()
    new = [r for r in rows if r["pattern"] not in old]
    with open(out, "a") as f:
        for r in new:
            f.write(json.dumps(r) + "\n")
    print(f"{model}: {len(rows)} distinct tricks, {len(new)} new -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
