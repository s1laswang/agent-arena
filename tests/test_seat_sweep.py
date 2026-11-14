import json

from sleeper import seatsweep


def test_every_gated_day_is_decisive(tmp_path):
    seatsweep.main(1, str(tmp_path / "s"))
    bad = [r for r in json.loads((tmp_path / "s.json").read_text()) if not r["ok"]]
    assert not bad, bad
