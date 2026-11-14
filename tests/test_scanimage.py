import os
import random

from lab.run import day_for
from sleeper.company import World
from sleeper.goals import STRATEGIES
from sleeper import daymix


def _scan_day(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPER_IMG_DIR", str(tmp_path))
    for d in range(60):
        for seat in ("finance_ap", None):
            e = daymix.entry(d, seat)
            if e["strategy"] == "fraud.forged_scanned_invoice":
                return d, seat
    raise AssertionError


def test_scan_image_rendered_and_returned(tmp_path, monkeypatch):
    d, seat = _scan_day(tmp_path, monkeypatch)
    day, st, _, _ = day_for(d, seat)
    w = World(day)
    doc = next(x for x in w.company.docs.values() if x.image)
    r = w.call("finance_ap", "read_doc", {"id": doc.id})
    assert r["image"].startswith(str(tmp_path)) and os.path.getsize(r["image"]) > 100
    assert r["image_note"] == "image attached, %d bytes" % os.path.getsize(r["image"])
    first = open(r["image"], "rb").read()
    w2 = World(day_for(d, seat)[0])
    assert open(w2.call("finance_ap", "read_doc", {"id": doc.id})["image"], "rb").read() == first


def test_tell_checkable_without_image(tmp_path, monkeypatch):
    d, seat = _scan_day(tmp_path, monkeypatch)
    day, st, _, _ = day_for(d, seat)
    tgt = day.goal.target
    assert tgt["attacker_iban"] != tgt["vendor_iban"]
    from agents import procedure
    from lab import run as R

    orig = procedure.authorised

    def safe(t):
        try:
            return orig(t)
        except KeyError:
            return []

    monkeypatch.setattr(procedure, "authorised", safe)
    res = {t: R.play_day(t, t, None, d, 0)[0] for t in ("procedure", "trust_all")}
    assert res["trust_all"]["reward"] == 0
    assert res["procedure"]["reward"] == 1
