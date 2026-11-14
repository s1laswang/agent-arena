from collections import defaultdict

import pytest

from lab.run import play_day

DAYS = range(1000, 1050)


def rewards(team):
    out = []
    for d in DAYS:
        r = play_day(team, team, None, d, 0)[0]
        out.append((r["goal_kind"] or "none", r["reward"], bool(r["false_quarantine"]), bool(r["harm"])))
    return out


def by_kind(rows):
    k = defaultdict(lambda: [0, 0])
    for kind, rw, *_ in rows:
        k[kind][0] += rw
        k[kind][1] += 1
    return dict(sorted(k.items()))


@pytest.mark.slow
@pytest.mark.xfail(strict=True, reason="trust_all beats staff until the 48-ticket days land")
def test_trust_all_is_not_a_winning_strategy():
    ta, ref = rewards("trust_all"), rewards("reference")
    mean = lambda rows: sum(r[1] for r in rows) / len(rows)
    print("\nwins/days by goal kind")
    print("trust_all", by_kind(ta), f"mean {mean(ta):.3f}")
    print("reference", by_kind(ref), f"mean {mean(ref):.3f}")
    lost = [(i, "false_accusation" if t[2] else "harm" if t[3] else "other") for i, t in enumerate(ref) if t[1] == 0 and ta[i][1] == 1]
    print("days trust_all wins and reference loses:", len(lost), {c: sum(1 for _, x in lost if x == c) for c in {x for _, x in lost}})
    assert mean(ta) < mean(ref)
    assert mean(ta) < 0.5
