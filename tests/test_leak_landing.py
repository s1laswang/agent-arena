import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import landing_table as L
from lab.run import day_for

DAYS = range(40)
LEAK = [d for d in DAYS if (g := day_for(d)[0].goal) is not None and g.kind == "leak"]


def test_leak_days_exist():
    assert len({day_for(d)[1].id for d in LEAK}) >= 3




@pytest.mark.parametrize("day_id", LEAK)
def test_landed_leak_scores_zero(day_id):
    r, sid = L.play(day_id, "staff")
    if r["landed"]:
        assert r["reward"] == 0, f"{sid} day {day_id} landed but reward 1, harm={r['harm']}"
