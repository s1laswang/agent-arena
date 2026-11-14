"""Leaderboard panel (v1.4 hard): fallback parsed from gap.md; source rows pass through unchanged."""
from canary.gemini import dashboard as dash
from canary.gemini import leaderboard as lb

GAP = """# Gap report

## v1.4 headline (runs committed 8fd4dec)
gemini-4-carbon, rules v1.4, dev seeds 0-29 per tier, every episode replay-verified:

| harness | tier | n | frontier / solver [95% CI] | luck-adjusted / solver [95% CI] |
|---|---|---|---|---|
| **OpenCode over MCP (the judges' harness)** | hard | 30 | **65% [24%, 98%]** | **72% [52%, 91%]** |
| OpenCode over MCP | medium | 30 | 111% [99%, 127%] | 101% [85%, 119%] |

The solver is paired on all 30 seeds per tier (solver means: hard 0.499, medium 0.645).

## Older section
| **OpenCode over MCP (the judges' harness)** | hard | 9 | 1% [0%, 2%] | 1% [0%, 2%] |
"""


def test_gap_fallback_rows():
    rows = lb.parse_gap(GAP)
    g, s = rows
    assert (g["name"], g["n"], g["pct_solver"], g["pct_solver_ci"]) == ("gemini-4-carbon", 30, 0.65, [0.24, 0.98])
    assert (g["luck_adjusted_pct_solver"], g["luck_adjusted_pct_solver_ci"]) == (0.72, [0.52, 0.91])
    assert g["compute"] is None  # gap.md does not state compute: never invented
    assert (s["name"], s["score"], s["n"]) == ("reference solver", 0.499, 30)


def test_source_rows_pass_through_as_is():
    src = {"rows": [{"name": "qwen2.5-7b-sft", "n": 30, "score": 0.21, "ci": [0.1, 0.3], "compute": "FR8", "gpu_hours": 12.5,
                     "eur": 31.0, "nested": {"x": 1}}]}
    out = dash.slim_leaderboard({"kind": "leaderboard", "source": "results/leaderboard_v14_hard.json", "source_sha": "abc",
                                 "source_json": src})
    r = out["rows"][0]
    assert r == {"name": "qwen2.5-7b-sft", "n": 30, "score": 0.21, "ci": [0.1, 0.3], "compute": "FR8", "gpu_hours": 12.5, "eur": 31.0}
    assert out["source_sha"] == "abc" and dash.slim_leaderboard(None) is None
