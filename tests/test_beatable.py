import json
from pathlib import Path

from sleeper.regret import run_day

ROWS = json.loads((Path(__file__).parent.parent / "results/attack/beatable.json").read_text())
KEPT = [r for r in ROWS if r["kept"]]


def test_kept_table():
    assert KEPT
    for r in KEPT:
        assert r["oracle"] == 1 and r["reference"] > r["staff"]


def test_kept_live():
    for r in KEPT[::6]:
        o = [run_day(s, "oracle", r["seat"], None, r["strategy"])["reward"] for s in (1, 2, 3)]
        f = [run_day(s, "reference", r["seat"], None, r["strategy"])["reward"] for s in (1, 2, 3)]
        t = [run_day(s, "staff", r["seat"], None, r["strategy"])["reward"] for s in (1, 2, 3)]
        assert sum(o) == 3 and sum(f) > sum(t)
