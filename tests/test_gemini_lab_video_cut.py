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


def test_plan_lands_inside_two_minutes():
    if not all((vc.NARR / f"{i}.wav").exists() for i in vc.VO_IDS):
        pytest.skip("narration clips not generated")
    tempo, starts, ends = vc.plan()
    assert tempo >= 1.0 and starts[0] > vc.COMMENTATOR_CUT
    assert all(b > a for a, b in zip(ends, starts[1:]))          # no overlapping lines
    assert ends[-1] <= vc.TOTAL - vc.END_HOLD + 1e-6


def test_gallery_numbers_sum():
    g = vc.gallery_numbers()
    assert g["episodes"] > 0 and g["cats"]
    assert abs(sum(c[2] for c in g["cats"]) - float(g["gap"])) < 0.01   # categories sum to the net gap


def test_resolved_script_has_no_placeholders(tmp_path: Path):
    if not (vc.NARR / "index.json").exists():
        pytest.skip("narration index not generated")
    out = vc.resolved_script(vc.ROOT / "docs/gemini/VIDEO-2MIN.md", tmp_path / "s.md")
    vo = [l for l in out.read_text().splitlines() if l.startswith("> VO[")]
    assert len(vo) == len(vc.VO_IDS) and not any("{" in l for l in vo)
