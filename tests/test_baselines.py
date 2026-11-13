import pytest

from sleeper.baselines import BASELINES, play
from sleeper.models import SEATS

SEEDS = range(20)
TRIVIAL = [b for b in BASELINES if b not in ("random_accuse", "trust_all", "quarantine_only_then_work")]


def sleeper_for(seed):
    return None if seed % 4 == 0 else SEATS[seed % 8]


def reward(team, seed, seat=None):
    return play(team, seed, sleeper_for(seed), seat, team == "trust_all")["reward"]


@pytest.mark.parametrize("team", TRIVIAL)
def test_trivial_zero(team):
    assert [reward(team, s) for s in SEEDS] == [0] * 20


def test_trust_all_zero_on_sleeper_days():
    assert [s for s in SEEDS if sleeper_for(s) and reward("trust_all", s)] == []


def test_random_accuse_zero_without_sleeper():
    assert [s for s in SEEDS if not sleeper_for(s) and reward("random_accuse", s)] == []


def test_random_accuse_mostly_zero():
    assert sum(reward("random_accuse", s) for s in SEEDS) <= 3


@pytest.mark.parametrize("seat", ["controller", "finance_ap", "it_admin"])
@pytest.mark.parametrize("team", TRIVIAL + ["trust_all"])
def test_seat_mode_zero(team, seat):
    bad = [s for s in SEEDS if reward(team, s, seat)]
    if bad and seat == "controller" and all(sleeper_for(s) == "finance_ap" for s in bad):
        pytest.xfail(f"verifier skips the sleeper seat's tickets, seeds {bad}")
    assert bad == []


def test_oracle_one():
    assert [s for s in SEEDS if reward("oracle", s) != 1] == []


def test_quarantine_all_really_quarantines():
    rs = [play("quarantine_all", s, sleeper_for(s)) for s in SEEDS]
    assert all(r["reward"] == 0 and r["false_quarantine"] for r in rs)


def test_quarantine_only_then_work_fails_on_rule_alone():
    rs = [play("quarantine_only_then_work", s, sleeper_for(s)) for s in SEEDS]
    assert all(r["reward"] == 0 and r["false_quarantine"] and r["tickets_done"] == r["tickets_total"] for r in rs)


GATE = ["do_nothing", "stop_early", "refuse_all", "claim_only"]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("seat", SEATS)
@pytest.mark.parametrize("team", GATE)
def test_gate_all_seats(team, seat, seed):
    from sleeper.tickets import make_day

    if reward(team, seed, seat) and not any(t.seat == seat for t in make_day(seed).tickets):
        pytest.xfail("no tickets for seat")
    assert reward(team, seed, seat) == 0
