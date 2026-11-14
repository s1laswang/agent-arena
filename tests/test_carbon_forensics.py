from __future__ import annotations

from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import re
import tokenize
from types import SimpleNamespace

from PIL import Image
import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.gemini import read_ledger
from canary.gemini.carbon_forensics import (
    DEFAULT_MODEL,
    FEATURE,
    FORENSIC_PROMPT,
    SUBROLE,
    analyze_carbon_chart_bytes,
    extract_carbon_trajectory,
    rational_ev_threshold,
    render_carbon_forensic_chart,
    score_carbon_diagnosis,
    select_carbon_episodes,
    shannon_entropy_bits,
    summarize_carbon_forensics,
)
from canary.gemini.provenance import scan_file_secrets
from canary.llm import MissingKeyError
from canary.rules import JUDGE_SEEDS, tier_params, tiers_version
from canary.solver.policy import SolverPolicy
from scripts.run_carbon_trajectory_forensics import run_carbon_forensics

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_OUT = REPO_ROOT / "results" / "gemini_roles" / "multimodal_evidence" / "carbon-trajectory-forensics"


class FakeServerError(RuntimeError):
    status_code = 503


class FakeModels:
    def __init__(self, payloads: list[dict | BaseException]):
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: list, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self._payloads.pop(0)
        if isinstance(item, BaseException):
            raise item
        usage = SimpleNamespace(
            prompt_token_count=1680,
            candidates_token_count=210,
            thoughts_token_count=340,
            cached_content_token_count=0,
        )
        return SimpleNamespace(text=json.dumps(item), usage_metadata=usage, candidates=[])


class FakeGenAIClient:
    def __init__(self, payloads: list[dict | BaseException]):
        self.models = FakeModels(payloads)


def _make_premature_hard_episode(seed: int = 2) -> dict:
    with tiers_version("v1.4"):
        env = Env("hard", seed)
        env.call("list_employees", {})
        env.call("status", {})
        ids = list(env._ids)
        mole = env._world.mole
        innocent = next(emp for emp in ids if emp != mole)
        env.call("plant_canary", {"doc_title": "Trap A", "assignment": {ids[0]: "A", ids[1]: "B", ids[2]: "C"}})
        env.call("plant_canary", {"doc_title": "Trap B", "assignment": {ids[3]: "A", ids[4]: "B", ids[5]: "C"}})
        env.call("advance_day", {})
        env.call("status", {})
        env.call("advance_day", {})
        env.call("check_leak_feed", {})
        env.call("accuse", {"employee": innocent})
        res = asdict(env.result(f"gemini:{DEFAULT_MODEL}"))
        return res


def _make_horizon_medium_episode(seed: int = 5) -> dict:
    with tiers_version("v1.4"):
        env = Env("medium", seed)
        env.call("list_employees", {})
        ids = list(env._ids)
        for day_idx in range(14):
            if day_idx < 4:
                env.call("plant_canary", {"doc_title": f"Memo {day_idx}", "assignment": {ids[0]: "A", ids[1]: "B"}})
            env.call("advance_day", {})
        res = asdict(env.result(f"gemini:{DEFAULT_MODEL}"))
        return res


def _make_clean_solver_episode(tier: str, seed: int) -> dict:
    with tiers_version("v1.4"):
        env = Env(tier, seed)
        pol = SolverPolicy(tier_params(tier))
        ep = run_episode(env, pol)
        raw = asdict(ep)
        raw["agent"] = f"gemini:{DEFAULT_MODEL}"
        return raw


@pytest.fixture(scope="module")
def sample_hard_traj_and_png(tmp_path_factory):
    out_png = tmp_path_factory.mktemp("charts") / "hard_2.png"
    traj = extract_carbon_trajectory(_make_premature_hard_episode(seed=2), source_file="hard-2/episodes.jsonl")
    png_bytes = render_carbon_forensic_chart(traj, out_path=out_png)
    return traj, png_bytes, out_png


def test_v14_hard_and_medium_trajectory_extraction_and_seed_hygiene(sample_hard_traj_and_png):
    traj_hard, _, _ = sample_hard_traj_and_png

    assert traj_hard.tier == "hard"
    assert traj_hard.tiers_version == "v1.4"
    assert len(traj_hard.employees) == 40
    assert traj_hard.horizon_days == 21
    assert traj_hard.max_canaries_per_day == 2
    assert traj_hard.max_daily_canaries_planted == 2
    assert traj_hard.actual_accuse_day == 3
    assert traj_hard.correct is False
    assert traj_hard.fooled_by_wrong_suspect is True
    assert traj_hard.accused_below_ev_threshold is True
    assert traj_hard.dev_seed_replayed is True
    assert traj_hard.true_mole is not None
    assert traj_hard.framed_decoy is not None
    assert traj_hard.true_mole_posterior is not None
    assert len(traj_hard.entropy_bits) == len(traj_hard.days) == 3
    assert len(traj_hard.solver_entropy_bits) == len(traj_hard.solver_days) >= 1
    for col_idx, tv in enumerate(traj_hard.true_v):
        col = [traj_hard.posterior_matrix[r][col_idx] for r in range(40)]
        assert sum(col) == pytest.approx(1.0, abs=1e-5)
        assert traj_hard.entropy_bits[col_idx] == pytest.approx(shannon_entropy_bits(col), abs=1e-6)
        assert traj_hard.ev_threshold[col_idx] == pytest.approx(rational_ev_threshold(tv, -1.0), abs=1e-9)

    med_ep = _make_horizon_medium_episode(seed=5)
    traj_med = extract_carbon_trajectory(med_ep, source_file="medium-5/episodes.jsonl")
    assert traj_med.tier == "medium"
    assert len(traj_med.employees) == 20
    assert traj_med.horizon_days == 14
    assert traj_med.end_reason == "horizon"
    assert traj_med.actual_accuse_day == 14
    assert traj_med.accused_below_ev_threshold is True
    assert traj_med.entropy_lags_solver is True

    judge_seed = min(JUDGE_SEEDS)
    with tiers_version("v1.4"):
        j_env = Env("medium", judge_seed)
        j_env.call("list_employees", {})
        j_env.call("accuse", {"employee": "e00"})
        j_ep = asdict(j_env.result(f"gemini:{DEFAULT_MODEL}"))
    j_traj = extract_carbon_trajectory(j_ep)
    assert j_traj.dev_seed_replayed is False
    assert j_traj.true_mole is None
    assert j_traj.framed_decoy is None
    assert j_traj.true_mole_posterior is None


def test_render_four_panel_chart_png(sample_hard_traj_and_png):
    _, png_bytes, out_png = sample_hard_traj_and_png

    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert out_png.is_file()
    assert out_png.read_bytes() == png_bytes

    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert img.size[0] >= 1800
    assert img.size[1] >= 2000


def test_analyze_chart_bytes_part_from_bytes_retries_and_keyless(tmp_path: Path, monkeypatch, sample_hard_traj_and_png):
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(led))
    monkeypatch.setenv("CANARY_LLM_MAX_RETRIES", "3")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)

    traj, png_bytes, _ = sample_hard_traj_and_png

    with pytest.raises(MissingKeyError):
        analyze_carbon_chart_bytes(png_bytes, max_retries=0)

    em_dash = chr(0x2014)
    fake_payload = {
        "accused_below_ev_threshold": True,
        "estimated_accuse_day": traj.actual_accuse_day,
        "hidden_bleed_gap_present": traj.hidden_bleed_gap_present,
        "entropy_lags_solver": traj.entropy_lags_solver,
        "fooled_step_summary": f"Panel 1 stays diffuse{em_dash}Panel 4 star sits below 1/(1+V).",
        "primary_failure_pattern": "premature_early_accusation",
    }
    client = FakeGenAIClient([FakeServerError("503 overloaded"), fake_payload])
    sleeps: list[float] = []
    diag, usage = analyze_carbon_chart_bytes(
        png_bytes,
        model_id=DEFAULT_MODEL,
        run_id="carbon-forensics-unit",
        chart_label="ep_0",
        sdk_client=client,
        sleep_fn=sleeps.append,
    )

    assert len(sleeps) == 1
    assert diag["accused_below_ev_threshold"] is True
    assert diag["estimated_accuse_day"] == traj.actual_accuse_day
    assert em_dash not in diag["fooled_step_summary"]
    assert usage["in"] == 1680
    assert usage["out"] == 210
    assert usage["thinking"] == 340
    assert usage["cost_usd"] > 0.0

    sent = client.models.calls[-1]
    assert sent["model"] == DEFAULT_MODEL
    parts = sent["contents"][0].parts
    assert len(parts) == 2
    assert parts[0].inline_data is not None
    assert parts[0].inline_data.mime_type == "image/png"
    assert parts[0].inline_data.data == png_bytes
    assert parts[1].text == FORENSIC_PROMPT
    assert not re.search(r"seed\s*=|0\.944|0\.503", parts[1].text)

    rows = read_ledger([led])
    assert [r["ok"] for r in rows] == [False, True]
    assert rows[-1]["feature"] == FEATURE
    assert rows[-1]["meta"]["subrole"] == SUBROLE


def test_end_to_end_runner_and_scoring_keyless(tmp_path: Path, monkeypatch):
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(led))

    runs_dir = tmp_path / "data" / "runs" / "committed" / "v1.4" / "gemini-4-carbon"
    ep_wrong_hard = _make_premature_hard_episode(seed=2)
    ep_wrong_med = _make_horizon_medium_episode(seed=5)
    ep_clean_med = _make_clean_solver_episode("medium", seed=2)
    for sub, ep in (("hard-2", ep_wrong_hard), ("medium-5", ep_wrong_med), ("medium-2", ep_clean_med)):
        d = runs_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "episodes.jsonl").write_text(json.dumps(ep) + "\n", encoding="utf-8")

    selected = select_carbon_episodes(runs_dir.parent, n_wrong=2, n_high=1)
    assert len(selected) == 3

    payloads = [
        {
            "accused_below_ev_threshold": t.accused_below_ev_threshold,
            "estimated_accuse_day": t.actual_accuse_day,
            "hidden_bleed_gap_present": t.hidden_bleed_gap_present,
            "entropy_lags_solver": t.entropy_lags_solver,
            "fooled_step_summary": "Panels 1 to 4 align cleanly with ground truth.",
            "primary_failure_pattern": (
                "none_justified_accusation" if t.correct else "horizon_below_ev_stall"
            ),
        }
        for t in selected
    ]
    out_dir = tmp_path / "out_forensics"
    res = run_carbon_forensics(
        runs_dir=runs_dir.parent,
        out_dir=out_dir,
        n_wrong=2,
        n_high=1,
        sdk_client=FakeGenAIClient(payloads),
        command_str="python scripts/run_carbon_trajectory_forensics.py",
        dpi=80,
    )

    meta = res["meta"]
    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "carbon_v14_trajectory_forensics"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["n_charts_analyzed"] == 3
    assert meta["visual_threshold_accuracy"] == 1.0
    assert meta["accuse_day_exact_accuracy"] == 1.0
    assert meta["hidden_bleed_gap_accuracy"] == 1.0
    assert meta["entropy_lag_accuracy"] == 1.0
    assert meta["outcome_pattern_accuracy"] == 1.0
    assert (out_dir / "meta.json").is_file()
    assert (out_dir / "diagnoses.json").is_file()
    assert (out_dir / "summary.md").is_file()
    assert len(list((out_dir / "charts").glob("*.png"))) == 3

    empty_agg = summarize_carbon_forensics([])
    assert empty_agg["n_charts_analyzed"] == 0
    sc = score_carbon_diagnosis(selected[0], payloads[0])
    assert sc["threshold_match"] is True


def test_committed_artifacts_and_source_hygiene():
    owned_sources = [
        REPO_ROOT / "canary" / "gemini" / "carbon_forensics.py",
        REPO_ROOT / "scripts" / "run_carbon_trajectory_forensics.py",
        REPO_ROOT / "tests" / "test_carbon_forensics.py",
    ]
    for src in owned_sources:
        text = src.read_text(encoding="utf-8")
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text
        assert chr(35) not in text, f"found literal hash character in {src}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == []
        assert scan_file_secrets(src, REPO_ROOT) == []

    if (COMMITTED_OUT / "meta.json").is_file():
        meta = json.loads((COMMITTED_OUT / "meta.json").read_text(encoding="utf-8"))
        diagnoses = json.loads((COMMITTED_OUT / "diagnoses.json").read_text(encoding="utf-8"))
        summary_md = (COMMITTED_OUT / "summary.md").read_text(encoding="utf-8")

        assert meta["role"] == "multimodal_evidence"
        assert meta["subrole"] == "carbon_v14_trajectory_forensics"
        assert meta["model_id"] == "gemini-4-carbon"
        assert 6 <= meta["n_charts_analyzed"] <= 8
        assert len(diagnoses) == meta["n_charts_analyzed"]
        assert meta["usage"]["in"] > 0
        assert meta["usage"]["out"] > 0
        assert chr(0x2014) not in summary_md
        assert chr(0x2013) not in summary_md

        for rec in diagnoses:
            chart_fp = COMMITTED_OUT / rec["chart_path"]
            assert chart_fp.is_file()
            raw = chart_fp.read_bytes()
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"
            assert hashlib.sha256(raw).hexdigest() == rec["chart_sha256"]

        for fp in COMMITTED_OUT.rglob("*"):
            if fp.is_file():
                assert scan_file_secrets(fp, REPO_ROOT) == []
