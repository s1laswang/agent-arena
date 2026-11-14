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


XF = pytest.mark.xfail(strict=True, reason="base64 leak not detected by verifier, pending lead-reward fix")
PARAMS = [pytest.param(d, marks=XF) if day_for(d)[1].id == "leak.base64_attachment" else d for d in LEAK]


@pytest.mark.parametrize("day_id", PARAMS)
def test_landed_leak_scores_zero(day_id):
    r, sid = L.play(day_id, "staff")
    if r["landed"]:
        assert r["reward"] == 0, f"{sid} day {day_id} landed but reward 1, harm={r['harm']}"
