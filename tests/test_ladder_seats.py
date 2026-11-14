import os

os.environ["GEMINI_API_KEY"] = ""

import pytest

from agents import ladder
from agents.staff import SEATS

DAYS = 10


@pytest.fixture(scope="module")
def tables():
    return {s: [r["mean"] for r in ladder.table(days=DAYS, start=1000, seat=s, jobs=4)[: len(ladder.RULES)]] for s in SEATS}


@pytest.mark.xfail(reason="not every ladder rule is exercised in every owning seat yet (lead-attack days work); flip when green", strict=False)
@pytest.mark.parametrize("seat", SEATS)
def test_owning_rule_lifts_seat(tables, seat):
    m = tables[seat]
    assert m == sorted(m)
    for k, owners in ladder.OWNERS.items():
        if seat in owners:
            assert m[k] > m[k - 1], (seat, k, m)
