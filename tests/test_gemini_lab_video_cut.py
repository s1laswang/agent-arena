"""canary.gemini.video_cut: timing plan, number parsers and the QA script (keyless, no rendering)."""
from pathlib import Path

import pytest

vc = pytest.importorskip("canary.gemini.video_cut")

SWARM_MD = """
| tier | attempts | best |
|---|---|---|
| hard | 50 | +0.750 |
| medium | 50 | +0.900 |

**4/4 attackers found it** on their own

| wave | run | planner models / executor | planned | finished | lost (infra-invalid) | MCP re-runs | tool calls | planner failures | invariant violations | flagged in-run | verified exploits | best | solver |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **all real waves** | | | 96 | 91 | 5 | 9 | 4325 | 17 | 0 | 1 | **0** | +0.720 | |
| wave 1 (whitebox) | swarm-a | x / y | 40 | 35 | 5 | 0 | 1225 | 6 | 0 | 0 | **0** | +0.000 | h |
| blackbox | swarm-b | x / y | 16 | 16 | 0 | 2 | 564 | 11 | 0 | 0 | **0** | +0.700 | h |
| wave 2 (escalation) | swarm-c | x / y | 24 | 24 | 0 | 4 | 1693 | 0 | 0 | 0 | **0** | +0.380 | h |
| wave 2b (escalation) | swarm-d | x / y | 16 | 16 | 0 | 3 | 843 | 0 | 0 | 1 | **0** | +0.720 | h |
"""


def test_swarm_numbers(tmp_path: Path):
    p = tmp_path / "swarm.md"
    p.write_text(SWARM_MD)
    s = vc.swarm_numbers(p)
    assert s["attempts"] == 100 and s["finished"] == 91 and s["mcp"] == 9 and s["exploits"] == 0
    assert len(s["waves"]) == 4 and s["whitebox"] == 75 and s["pc"] == (4, 4)


def _silent_wav(path: Path, seconds: float, rate: int = 24000) -> None:
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))


def test_layout_lengths_follow_clips():
    shots = [vc.Shot("a", "a", lead=0.5, min_dur=20.0), vc.Shot("b", "b"), vc.Shot("c", fixed=5.9), vc.Shot("d", "d", tail=2.2)]
    slots = vc.layout(shots, 1.0, {"a": 10.0, "b": 8.0, "d": 4.0})
    assert [round(s.t1 - s.t0, 2) for s in slots] == [20.0, 8.45, 5.9, 6.43]
    assert all(s.t1 == n.t0 for s, n in zip(slots, slots[1:]))                    # contiguous
    assert slots[0].vs == 0.5 and slots[2].vs == slots[2].t0                    # VO-less shot has no VO window


def test_plan_speeds_up_only_when_over_budget(tmp_path: Path):
    for k, d in {"a": 10.0, "b": 60.0}.items():
        _silent_wav(tmp_path / f"{k}.wav", d)
    shots = [vc.Shot("a", "a", min_dur=20.0), vc.Shot("b", "b", tail=2.2)]
    tempo, slots = vc.plan(shots, max_total=200.0, narr=tmp_path)
    assert tempo == 1.0 and slots[-1].t1 < 200
    tempo, slots = vc.plan(shots, max_total=70.0, narr=tmp_path)
    assert tempo > 1.0 and abs(slots[-1].t1 - 70.0) < 1e-3 and slots[0].t1 == 20.0


def test_v2_plan_fits_spec():
    shots = vc.shots_v2(vc.xprov_available())
    if not all((vc.NARR / f"{s.vo}.wav").exists() for s in shots if s.vo):
        pytest.skip("narration clips not generated")
    tempo, slots = vc.plan(shots)
    by = {s.shot.key: s for s in slots}
    assert tempo >= 1.0 and slots[-1].t1 <= 140.0
    assert slots[0].shot.key == "holdup" and slots[0].t1 - slots[0].t0 >= vc.HOLDUP_SECONDS
    assert "problem" not in by and by["live"].t0 < by["ladder"].t0
    vo = [s for s in slots if s.shot.vo]
    assert all(b.vs > a.ve for a, b in zip(vo, vo[1:]))                          # no overlapping lines
    assert all(s.t0 <= s.vs and s.ve <= s.t1 for s in vo)                       # each line inside its shot


def test_ladder_numbers_parse_committed_table():
    L = vc.ladder_numbers()
    assert L["episodes"] > 0
    for k in ("carbon", "flash"):
        assert L[k]["n"] > 0 and L[k]["usd"] > 0 and "%" in L[k]["ratio"] and "[" in L[k]["ratio"]


def test_holdup_segment_is_committed_and_short():
    assert vc.HOLDUP_CLIP.exists() and vc.HOLDUP_CLIP.stat().st_size < 15e6


def test_gallery_numbers_sum():
    g = vc.gallery_numbers()
    assert g["episodes"] > 0 and g["cats"]
    assert abs(sum(c[2] for c in g["cats"]) - float(g["gap"])) < 0.01   # categories sum to the net gap


def test_resolved_script_has_no_placeholders(tmp_path: Path):
    if not (vc.NARR / "index.json").exists():
        pytest.skip("narration index not generated")
    out = vc.resolved_script(vc.ROOT / "docs/gemini/VIDEO-2MIN.md", tmp_path / "s.md")
    vo = [l for l in out.read_text().splitlines() if l.startswith("> VO[")]
    ids = [l[5:l.index("]")] for l in vo]
    want = [s.vo for s in vc.shots_v2(vc.xprov_available()) if s.vo]
    assert ids == want and not any("{" in l for l in vo)
    assert "seven hundred fifty-four" in vo[0] and "strength" in vo[0]
