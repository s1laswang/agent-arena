import json
import sys
from pathlib import Path

from agents import gemini

if len(sys.argv) != 4:
    sys.exit("usage: gemini_budget.py DAYS TRIALS TEAMS   (TEAMS = number of Gemini-played teams per day)")
days, trials, teams = map(int, sys.argv[1:])
per_day = gemini.estimate_calls()
calls = days * trials * teams * per_day
print("calls per team-day (upper bound, SLEEPER_SEATS x ROUNDS x STEPS): %d" % per_day)
print("estimated calls: %d" % calls)
log = gemini.CACHE / "usage.jsonl"
rows = [json.loads(l) for l in log.read_text().splitlines()] if log.is_file() else []
if rows:
    ai = sum(r["in"] for r in rows) / len(rows)
    ao = sum(r["out"] for r in rows) / len(rows)
    print("measured from %d live calls: %.0f in, %.0f out tokens per call" % (len(rows), ai, ao))
    print("estimated tokens: %.0f in, %.0f out" % (ai * calls, ao * calls))
else:
    print("tokens per call: NOT FOUND (no live calls logged yet)")
cap = int(__import__("os").environ.get("SLEEPER_MAX_CALLS", 0) or 0)
if cap and cap < calls:
    print("WARNING: SLEEPER_MAX_CALLS=%d is below the estimate" % cap)
