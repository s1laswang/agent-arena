from __future__ import annotations

import io
import json
import math
import sys
import tokenize
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import run_carbon_hard_thinking as rcht
import verify_replay
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.gemini.roles_dashboard import SECRET_RE, _scan_run_for_secrets
from canary.rules import tier_params
from canary.solver.policy import SolverPolicy


def test_stub_end_to_end_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    out_dir = tmp_path / "thinking-ladder-carbon-hard0"
    rc = rcht.main(["--stub", "--out", str(out_dir)])
    assert rc == 0

    meta_path = out_dir / "meta.json"
    comp_path = out_dir / "comparison.json"
    summary_path = out_dir / "summary.md"
    assert meta_path.exists()
    assert comp_path.exists()
    assert summary_path.exists()
    assert (out_dir / "low" / "episodes.jsonl").exists()
    assert (out_dir / "low" / "level_meta.json").exists()
    assert not (out_dir / "low" / "meta.json").exists()
    assert (out_dir / "low" / "transcripts" / "0.json").exists()
    assert (out_dir / "high" / "episodes.jsonl").exists()
    assert (out_dir / "high" / "level_meta.json").exists()
    assert not (out_dir / "high" / "meta.json").exists()
    assert (out_dir / "high" / "transcripts" / "0.json").exists()

    assert verify_replay.main([str(out_dir)]) == 0
    assert _scan_run_for_secrets(out_dir) is False
    for fp in out_dir.rglob("*"):
        if fp.is_file():
            assert scan_file_secrets(fp, tmp_path) == []

    low_tx = (out_dir / "low" / "transcripts" / "0.json").read_text()
    assert "thought_signature_sha256" in low_tx
    assert '"thought_signature":' not in low_tx

    meta = json.loads(meta_path.read_text())
    required_keys = {
        "role",
        "subrole",
        "model_id",
        "tiers_version",
        "commit",
        "timestamp",
        "command",
        "usage",
        "low_score",
        "high_score",
        "solver_score",
    }
    assert required_keys <= set(meta.keys())
    assert meta["role"] == "investigators"
    assert meta["subrole"] == "hard_thinking_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["episode_count"] == 2
    assert meta["stub"] is True
    assert meta["replay_verified"] is True

    expected_solver = run_episode(Env("hard", 0), SolverPolicy())
    assert abs(meta["solver_score"] - expected_solver.score) < 1e-9

    comp = json.loads(comp_path.read_text())
    assert comp["tier_params"]["n_employees"] == 40
    assert comp["tier_params"]["n_days"] == 21
    assert comp["tier_params"]["canaries_per_day"] == 2
    assert comp["high"]["usage"]["thinking"] > comp["low"]["usage"]["thinking"]
    assert (
        comp["high"]["canary_partition"]["mean_recipient_entropy_bits"]
        > comp["low"]["canary_partition"]["mean_recipient_entropy_bits"]
    )
    assert "premature_accusation" in comp["low"]["regret"]["tag_counts"]
    assert "uninformative_canary" in comp["low"]["regret"]["tag_counts"]
    assert comp["low"]["accusation_calibration"]["p_accused"] is not None
    assert comp["high"]["accusation_calibration"]["p_accused"] is not None

    ledger_rows = [json.loads(line) for line in ledger_file.read_text().splitlines() if line.strip()]
    assert len(ledger_rows) == comp["low"]["usage"]["calls"] + comp["high"]["usage"]["calls"]
    assert all(r["feature"] == "investigators" and r["model"] == "gemini-4-carbon" for r in ledger_rows)

    for text_path in (meta_path, comp_path, summary_path):
        txt = text_path.read_text()
        assert "\u2014" not in txt
        assert "\u2013" not in txt


def test_canary_partition_entropy_math():
    assert rcht.shannon_entropy_bits([]) == 0.0
    assert rcht.shannon_entropy_bits([5.0]) == 0.0
    assert abs(rcht.shannon_entropy_bits([1.0, 1.0, 1.0]) - math.log2(3.0)) < 1e-9

    env = Env("hard", 0)
    env.call("list_employees", {})
    env.call("plant_canary", {"doc_title": "Equal 3", "assignment": {"e00": "A", "e01": "B", "e02": "C"}})
    ep = env.result("probe")
    part = rcht.analyze_canary_partitions(ep, tier_params("hard"))
    assert part["canaries_planted"] == 1
    assert abs(part["mean_recipient_entropy_bits"] - round(math.log2(3.0), 4)) < 1e-6
    assert part["mean_posterior_entropy_bits"] > 0.0


def test_real_client_builder_sets_thinking_level_and_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    fake_sdk = types.SimpleNamespace(
        models=types.SimpleNamespace(
            generate_content=lambda **kw: types.SimpleNamespace(
                candidates=[
                    types.SimpleNamespace(
                        finish_reason="STOP",
                        content=types.SimpleNamespace(
                            parts=[types.SimpleNamespace(text="ok", thought=False, function_call=None)],
                            model_dump=lambda **mkw: {"role": "model", "parts": [{"text": "ok"}]},
                        ),
                    )
                ],
                usage_metadata=types.SimpleNamespace(
                    prompt_token_count=50,
                    candidates_token_count=10,
                    thoughts_token_count=120,
                    cached_content_token_count=0,
                ),
                model_version="gemini-4-carbon-001",
            )
        )
    )

    low_c = rcht.build_real_client(
        "gemini-4-carbon", "low", "run:low", {"thinking_level": "low"}, max_retries=10, sdk_client=fake_sdk
    )
    high_c = rcht.build_real_client(
        "gemini-4-carbon", "high", "run:high", {"thinking_level": "high"}, max_retries=10, sdk_client=fake_sdk
    )
    assert low_c.thinking_level == "low"
    assert high_c.thinking_level == "high"
    assert low_c.inner.inner.max_retries == 10
    assert high_c.inner.inner.max_retries == 10

    req_low = low_c.build_request([{"role": "user", "content": "hi"}], None, 0.0, None, None, None)
    req_high = high_c.build_request([{"role": "user", "content": "hi"}], None, 0.0, None, None, None)
    assert "LOW" in str(req_low["config"].thinking_config.thinking_level)
    assert "HIGH" in str(req_high["config"].thinking_config.thinking_level)
    assert req_low["config"].thinking_config.include_thoughts is True
    assert req_high["config"].thinking_config.include_thoughts is True

    resp = high_c.chat([{"role": "user", "content": "hi"}])
    assert resp.text == "ok"
    assert high_c.tally["thinking"] == 120
    assert high_c.tally["model_version"] == "gemini-4-carbon-001"


def test_resume_reuses_valid_episodes(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    out_dir = tmp_path / "out"
    assert rcht.main(["--stub", "--out", str(out_dir)]) == 0
    first_count = len(ledger_file.read_text().splitlines())
    assert first_count > 0

    assert rcht.main(["--stub", "--resume", "--out", str(out_dir)]) == 0
    second_count = len(ledger_file.read_text().splitlines())
    assert second_count == first_count


def test_source_files_have_no_comments_em_dashes_or_secrets():
    for path in (
        ROOT / "scripts" / "run_carbon_hard_thinking.py",
        ROOT / "tests" / "test_carbon_hard_thinking.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == []
        assert scan_file_secrets(path, ROOT) == []
        assert SECRET_RE.search(text) is None


def test_committed_hard_seed0_run_folder_verified():
    run_dir = ROOT / "results" / "gemini_roles" / "investigators" / "thinking-ladder-carbon-hard0"
    assert (run_dir / "meta.json").is_file()
    assert (run_dir / "comparison.json").is_file()
    assert (run_dir / "summary.md").is_file()
    assert (run_dir / "low" / "episodes.jsonl").is_file()
    assert (run_dir / "high" / "episodes.jsonl").is_file()
    assert not (run_dir / "low" / "meta.json").exists()
    assert not (run_dir / "high" / "meta.json").exists()

    assert verify_replay.main([str(run_dir)]) == 0
    assert _scan_run_for_secrets(run_dir) is False

    inspected = _inspect_run(run_dir / "meta.json", ROOT, ROOT / "data" / "runs" / "committed" / "v1.4")
    assert inspected["verified"] is True
    assert inspected["errors"] == []
    assert inspected["secret_leaks"] == []
    assert inspected["role"] == "investigators"
    assert inspected["model_id"] == "gemini-4-carbon"
    assert inspected["count"] == 2
    assert inspected["thinking_tokens"] > 0

    for fp in run_dir.rglob("*"):
        if fp.is_file():
            txt = fp.read_text(encoding="utf-8")
            assert "\u2014" not in txt
            assert "\u2013" not in txt
            assert scan_file_secrets(fp, ROOT) == []
