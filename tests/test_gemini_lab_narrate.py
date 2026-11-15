"""Canary Lab narration (G5): VIDEO.md parsing and placeholder filling, keyless."""
import io
import wave
from pathlib import Path

import pytest

from canary.gemini import narrate

ROOT = Path(__file__).resolve().parents[1]
FX = Path(__file__).parent / "fixtures" / "gemini_lab"
VIDEO = ROOT / "docs" / "gemini" / "VIDEO.md"


def _fixture_results(tmp_path):
    """Fixture results plus the final-shape files VIDEO.md now speaks from (blind atlas, reviewed swarm)."""
    import json
    import shutil
    res = tmp_path / "results"
    shutil.copytree(FX / "results", res)
    (res / "atlas_blind.json").write_text(json.dumps({"corpus": {"episodes": 10}, "modes": [{"id": "n", "name": "N"}],
        "recovery": {"tags": {}, "tags_recovered": ["a"], "n_tags": 2, "novel_modes": ["n"], "regret_share_covered": 0.3}}))
    S = json.loads((res / "swarm.json").read_text())
    tier = (S.get("attempts") or [{}])[0].get("tier") or "medium"
    S["per_tier"] = {tier: {"best_unjustified": 0.1, "best_unjustified_attempt": "x", "solver_mean_paired": 0.5}}
    S["positive_control"] = {"attempts": 2, "attackers_found": 2}
    (res / "swarm.json").write_text(json.dumps(S))
    L = json.loads((res / "ladder.json").read_text())
    key = "rows" if "rows" in L else "cells"
    tier = "hard" if any(c.get("tier") == "hard" for c in L[key]) else L[key][0]["tier"]
    L[key] = [c for c in L[key] if not (c.get("tier") == tier and c.get("model") in ("gemini-4-carbon", "gemini-3.5-flash")
                                         and c.get("level", c.get("thinking_level")) == "high")]
    for m, r, cost in (("gemini-4-carbon", 1.0, 2.0), ("gemini-3.5-flash", 0.7, 0.5)):
        L[key].append({"model": m, "level": "high", "tier": tier, "n": 10, "ratio": r, "ratio_lo": r - 0.2,
                       "ratio_hi": r + 0.2, "cost_per_ep": cost})
    (res / "ladder.json").write_text(json.dumps(L))
    return res


def test_video_script_fills_from_fixtures(tmp_path):
    vals = narrate.values(_fixture_results(tmp_path), [FX / "ledger"])
    clips = narrate.script(VIDEO, vals)
    ids = [c["id"] for c in clips]
    assert ids[0] == "01-hook" and ids[-1] == "06-close" and len(ids) == len(set(ids)) >= 6
    text = " ".join(c["text"] for c in clips)
    assert "{" not in text and "pending" not in text
    assert 100 < sum(c["est_s"] for c in clips) <= 180  # fits the 3-minute cut


def test_missing_results_stop_unless_allowed(tmp_path):
    vals = narrate.values(tmp_path, [tmp_path])
    with pytest.raises(SystemExit):
        narrate.script(VIDEO, vals)
    assert any("pending" in c["text"] for c in narrate.script(VIDEO, vals, allow_pending=True))


def test_spoken_formats_and_wav(tmp_path):
    assert narrate.say_model("gemini-3.8-flash") == "Gemini 3.8 Flash"
    assert narrate.say_tokens(2_900_000) == "2.9 million" and narrate.say_pct(0.834) == "83 percent"
    assert narrate.say_score(-0.2) == "minus 0.20"
    p = tmp_path / "a.wav"
    assert narrate.write_wav(p, b"\0\0" * 24000, 24000) == pytest.approx(1.0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(b"\0\0" * 12000)
    assert narrate.write_wav(tmp_path / "b.wav", buf.getvalue(), 0) == pytest.approx(0.5)


def test_named_cells_spoken_with_n_ci_cost_and_served_name():
    cells = [{"model": "gemini-4-carbon", "level": "high", "tier": "hard", "n": 10, "pct_solver": 1.06, "ratio_lo": 0.94,
              "ratio_hi": 1.26, "cost_usd_per_episode": 1.931},
             {"model": "gemini-3.5-flash", "level": "high", "tier": "hard", "n": 20, "pct_solver": 0.71, "ratio_lo": 0.11,
              "ratio_hi": 1.58, "cost_usd_per_episode": 0.425, "model_versions": ["gemini-3.6-flash"]},
             {"model": "gemini-4-argon", "level": "high", "tier": "hard", "n": 2, "pct_solver": 1.5, "ratio_lo": 1, "ratio_hi": 2}]
    lead = narrate.cell_values(cells, "lead", "gemini-4-carbon", "high", "hard")
    cheap = narrate.cell_values(cells, "cheap", "gemini-3.5-flash", "high", "hard")
    assert (lead["lead_pct"], lead["lead_ci"], lead["lead_n"], lead["lead_cost"]) == ("106 percent", "94 percent to 126 percent", "10", "1.93 dollars")
    assert cheap["cheap_model"] == "Gemini 3.6 Flash" and cheap["cheap_ci"] == "11 percent to 158 percent"
    assert narrate.cell_values(cells, "x", "gemini-4-argon", "high", "hard") == {}  # n=2 is never spoken


def test_frontier_never_speaks_small_n_cells():
    cells = [{"model": "gemini-4-argon", "level": "low", "tier": "hard", "n": 2, "pct_solver": 1.4, "cost_usd_per_episode": 0.1},
             {"model": "gemini-3.5-flash", "level": "high", "tier": "hard", "n": 8, "pct_solver": 1.017, "ratio_lo": 0.84,
              "ratio_hi": 1.29, "cost_usd_per_episode": 0.342, "model_versions": ["gemini-3.6-flash"]},
             {"model": "gemini-4-carbon", "level": "default", "tier": "hard", "n": 10, "pct_solver": 0.66, "cost_usd_per_episode": 1.571}]
    v = narrate.frontier_values(cells, "hard")
    assert v["frontier_model"].startswith("Gemini 3.5 Flash, served as Gemini 3.6 Flash")
    assert (v["frontier_pct"], v["frontier_n"], v["frontier_cost_share"]) == ("102 percent", "8", "22 percent")
    assert v["frontier_ci"] == "84 percent to 129 percent" and v["frontier_ref"] == "Gemini 4 Carbon at its default"
    assert narrate.frontier_values(cells[:1], "hard") == {}


def test_blind_atlas_and_committed_ledger_values(tmp_path):
    import gzip
    import json
    import shutil
    res = tmp_path / "results"
    shutil.copytree(FX / "results", res)
    (res / "atlas_blind.json").write_text(json.dumps({"corpus": {"episodes": 153}, "modes": [{"id": "n", "name": "N"}],
        "recovery": {"tags": {}, "tags_recovered": ["a", "b", "c"], "n_tags": 5, "novel_modes": ["n"], "regret_share_covered": 0.21}}))
    row = {"ts": 1.0, "feature": "x", "model": "m", "in": 10, "out": 1, "ok": True, "pid": 1, "host": "h"}
    with gzip.open(res / "usage_ledger.jsonl.gz", "wt") as f:
        f.write(json.dumps(row) + "\n")
    v = narrate.values(res, ["committed"])
    assert (v["blind_recovered"], v["blind_tags"], v["blind_new"], v["blind_regret_covered"]) == ("3", "5", "1", "21 percent")
    assert v["calls"] == "1"
