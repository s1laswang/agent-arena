from __future__ import annotations

import dataclasses
import io
import json
import struct
import tokenize
from pathlib import Path

import pytest

from canary.analysis.accuse import audit_episode
from canary.baselines import DoNothing, StopEarly
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import calibration
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))


def _png_dimensions(png_path: Path) -> tuple[int, int]:
    raw = png_path.read_bytes()
    assert raw[:8] == PNG_MAGIC
    assert raw[12:16] == b"IHDR"
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


def test_break_even_threshold_and_ev_identities():
    assert calibration.break_even_threshold(1.0) == pytest.approx(0.5)
    assert calibration.break_even_threshold(0.6) == pytest.approx(0.625)
    assert calibration.break_even_threshold(0.25) == pytest.approx(0.8)
    assert calibration.break_even_threshold(0.0) == pytest.approx(1.0)

    prev = 2.0
    for v_int in range(0, 21):
        v = v_int / 20.0
        thr = calibration.break_even_threshold(v)
        assert 0.5 <= thr <= 1.0
        assert thr < prev
        prev = thr
        assert calibration.expected_accuse_ev(thr, v) == pytest.approx(0.0, abs=1e-12)
        assert calibration.premature_ev_loss(thr, v) == 0.0

    p_low = 0.2
    v_val = 0.6
    thr_val = calibration.break_even_threshold(v_val)
    ev_low = calibration.expected_accuse_ev(p_low, v_val)
    assert ev_low == pytest.approx(0.2 * 0.6 - 0.8)
    assert ev_low < 0.0
    assert calibration.premature_ev_loss(p_low, v_val) == pytest.approx(-ev_low)
    assert calibration.premature_ev_loss(p_low, v_val) == pytest.approx((1.0 + v_val) * (thr_val - p_low))

    p_high = 0.9
    ev_high = calibration.expected_accuse_ev(p_high, v_val)
    assert ev_high == pytest.approx(0.9 * 0.6 - 0.1)
    assert ev_high > 0.0
    assert calibration.premature_ev_loss(p_high, v_val) == 0.0
    assert calibration.premature_ev_loss(None, v_val) == 0.0

    with pytest.raises(ValueError):
        calibration.break_even_threshold(-0.01)
    with pytest.raises(ValueError):
        calibration.break_even_threshold(0.5, wrong_score=0.0)
    with pytest.raises(ValueError):
        calibration.expected_accuse_ev(1.05, 0.8)
    with pytest.raises(ValueError):
        calibration.expected_accuse_ev(-0.05, 0.8)


def test_posterior_bounds_and_accuse_parity_on_env_episodes():
    early_ep = run_episode(Env("medium", 2), StopEarly(seed=2))
    rec_early = calibration.analyze_episode(early_ep)
    assert rec_early["did_accuse"] is True
    assert rec_early["n_employees"] == 20
    assert all(0.0 <= p <= 1.0 for p in rec_early["posterior"].values())
    assert sum(rec_early["posterior"].values()) == pytest.approx(1.0, abs=1e-9)
    assert rec_early["p_accused"] == pytest.approx(1.0 / 20.0, abs=1e-9)
    assert rec_early["v_true"] == pytest.approx(1.0)
    assert rec_early["threshold"] == pytest.approx(0.5)
    assert rec_early["premature_commit"] is True
    assert rec_early["ev_lost"] == pytest.approx(0.90)
    assert round(rec_early["p_accused"], 3) == audit_episode(early_ep)["p_accused"]

    solver_ep = run_episode(Env("easy", 1), SolverPolicy(None))
    rec_solver = calibration.analyze_episode(solver_ep)
    assert rec_solver["did_accuse"] is True
    assert 0.0 <= rec_solver["p_accused"] <= rec_solver["p_top"] <= 1.0
    assert sum(rec_solver["posterior"].values()) == pytest.approx(1.0, abs=1e-9)
    assert rec_solver["p_accused"] >= rec_solver["threshold"]
    assert rec_solver["premature_commit"] is False
    assert rec_solver["ev_lost"] == 0.0
    assert round(rec_solver["p_accused"], 3) == audit_episode(solver_ep)["p_accused"]

    abstain_ep = run_episode(Env("medium", 3), DoNothing(seed=3))
    rec_abstain = calibration.analyze_episode(abstain_ep)
    assert rec_abstain["did_accuse"] is False
    assert rec_abstain["accused"] is None
    assert rec_abstain["p_accused"] is None
    assert 0.0 < rec_abstain["p_top"] <= 1.0
    assert sum(rec_abstain["posterior"].values()) == pytest.approx(1.0, abs=1e-9)
    assert rec_abstain["decision_step"] == len(abstain_ep.steps)
    assert 0.5 <= rec_abstain["threshold"] <= 1.0
    assert rec_abstain["premature_commit"] is False
    assert rec_abstain["ev_lost"] == 0.0


def test_exact_step_truncates_anything_after_accuse():
    extra_steps = [
        Step(t=0, day=1, tool="status", args={}, result={"ok": True, "data": {"day": 1, "V": 0.8}}),
        Step(t=1, day=1, tool="accuse", args={"employee": "e02"}, result={"ok": True, "data": {"accused": "e02", "episode_over": True}}),
        Step(
            t=2,
            day=2,
            tool="check_leak_feed",
            args={},
            result={"ok": True, "data": {"items": [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]}},
        ),
    ]
    ep = EpisodeResult(
        tier="easy",
        seed=0,
        agent="gemini:gemini-4-carbon",
        steps=extra_steps,
        score=-1.0,
        accused="e02",
        correct=False,
        final_day=1,
        end_reason="accused",
        meta={"V": 0.8},
    )
    rec = calibration.analyze_episode(ep)
    assert rec["decision_step"] == 1
    assert rec["decision_day"] == 1
    assert rec["p_accused"] == pytest.approx(1.0 / 12.0, abs=1e-9)
    assert rec["threshold"] == pytest.approx(1.0 / 1.8)
    assert rec["premature_commit"] is True


def test_cli_end_to_end_png_and_filtering(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")

    runs_dir = tmp_path / "runs"
    out_dir = tmp_path / "out"

    gem_high = dataclasses.asdict(run_episode(Env("easy", 0), SolverPolicy(None)))
    gem_high["agent"] = "gemini:gemini-4-carbon"
    gem_high["meta"]["ladder"] = {"model": "gemini-4-carbon", "thinking_level": "high"}

    gem_low = dataclasses.asdict(run_episode(Env("medium", 1), StopEarly(seed=1)))
    gem_low["agent"] = "gemini:gemini-4-carbon"
    gem_low["meta"]["ladder"] = {"model": "gemini-4-carbon", "thinking_level": "low"}

    front_prem = dataclasses.asdict(run_episode(Env("medium", 2), StopEarly(seed=2)))
    front_prem["agent"] = "openai:gpt-5.5"

    front_abs = dataclasses.asdict(run_episode(Env("medium", 4), DoNothing(seed=4)))
    front_abs["agent"] = "grok"

    bad_error = dict(front_prem, seed=99, end_reason="error", meta={"valid": False, "error": "timeout"})
    superseded_ep = dict(front_prem, seed=88)
    ref_solver = dataclasses.asdict(run_episode(Env("easy", 0), SolverPolicy(None)))
    ref_solver["agent"] = "solver"

    _write_jsonl(runs_dir / "v1.4" / "gemini-high" / "episodes.jsonl", [gem_high])
    _write_jsonl(runs_dir / "v1.4" / "gemini-low" / "episodes.jsonl", [gem_low, bad_error])
    _write_jsonl(runs_dir / "v1.4" / "openai" / "episodes.jsonl", [front_prem])
    _write_jsonl(runs_dir / "v1.4" / "grok" / "episodes.jsonl", [front_abs])
    _write_jsonl(runs_dir / "superseded" / "old" / "episodes.jsonl", [superseded_ep])
    _write_jsonl(runs_dir / "v1.4" / "reference" / "solver" / "episodes.jsonl", [ref_solver])

    rc = calibration.main(["--runs-dir", str(runs_dir), "--out", str(out_dir), "--bins", "5"])
    assert rc == 0

    json_path = out_dir / "calibration.json"
    md_path = out_dir / "calibration.md"
    png_path = out_dir / "calibration_curve.png"
    assert json_path.exists() and json_path.stat().st_size > 100
    assert md_path.exists() and md_path.stat().st_size > 100
    assert png_path.exists() and png_path.stat().st_size > 1000

    w, h = _png_dimensions(png_path)
    assert w > 600 and h > 250

    doc = json.loads(json_path.read_text())
    s = doc["summary"]
    assert s["n_episodes"] == 4
    assert s["n_accused"] == 3
    assert s["n_abstained"] == 1
    assert s["premature_count"] == 2
    assert s["ev_lost_total"] > 1.5
    assert s["mean_gated_ev"] - s["mean_ev"] == pytest.approx(s["ev_lost_per_episode"], abs=1e-9)
    assert len(doc["bins"]) == 5
    assert sum(b["count"] for b in doc["bins"]) == s["n_accused"]
    assert len(doc["reference_benchmarks"]) == 1
    assert doc["reference_benchmarks"][0]["agent"] == "solver"
    assert set(doc["by_family"].keys()) == {"gemini", "frontier"}

    md_text = md_path.read_text()
    assert "gemini:gemini-4-carbon" in md_text
    assert "calibration_curve.png" in md_text
    assert "\u2014" not in md_text
    assert "\u2013" not in md_text

    loaded = calibration.load_episodes(runs_dir, include_reference=False)
    assert len(loaded) == 4
    loaded_all = calibration.load_episodes(runs_dir, include_reference=True)
    assert len(loaded_all) == 5

    empty_out = tmp_path / "empty_out"
    empty_rep = calibration.run_calibration(runs_dir=tmp_path / "missing_dir", out_dir=empty_out)
    assert empty_rep["summary"]["n_episodes"] == 0
    ew, eh = _png_dimensions(empty_out / "calibration_curve.png")
    assert ew > 600 and eh > 250


def test_committed_runs_calibration_invariants(tmp_path):
    committed = REPO_ROOT / "data" / "runs" / "committed"
    if not committed.exists():
        pytest.skip("committed runs directory not present")
    out_dir = tmp_path / "committed_cal"
    rep = calibration.run_calibration(runs_dir=committed, out_dir=out_dir)
    assert rep["summary"]["n_episodes"] > 0
    for ep in rep["episodes"]:
        assert 0.5 <= ep["threshold"] <= 1.0
        assert ep["threshold"] == pytest.approx(1.0 / (1.0 + ep["v_true"]))
        assert 0.0 <= ep["p_top"] <= 1.0
        assert sum(ep["posterior"].values()) == pytest.approx(1.0, abs=1e-9)
        assert all(0.0 <= p <= 1.0 for p in ep["posterior"].values())
        if ep["did_accuse"]:
            assert 0.0 <= ep["p_accused"] <= ep["p_top"] + 1e-9
            if ep["premature_commit"]:
                assert ep["p_accused"] < ep["threshold"]
                assert ep["ev_lost"] > 0.0
            else:
                assert ep["ev_lost"] == 0.0
        else:
            assert ep["p_accused"] is None
            assert ep["ev_lost"] == 0.0
    w, h = _png_dimensions(out_dir / "calibration_curve.png")
    assert w > 600 and h > 250


def test_no_comments_and_no_em_dashes():
    targets = [
        REPO_ROOT / "canary" / "gemini" / "calibration.py",
        REPO_ROOT / "tests" / "test_calibration_analysis.py",
    ]
    for path in targets:
        src = path.read_text()
        assert "\u2014" not in src
        assert "\u2013" not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment tokens in {path}: {comments}"
