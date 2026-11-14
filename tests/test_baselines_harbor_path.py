from sleeper.baselines_harbor import NAMES, bad, run


def test_baselines_zero_oracle_one_via_sidecar():
    rows = run([1000, 1001], names=NAMES, workers=4)
    assert len(rows) == len(NAMES) * 2 * 2
    assert bad(rows) == []
