"""Fast offline tests for scripts.run_v16_social_audit and fresh CI fallback."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import pytest

from canary import llm as canary_llm
from canary.baselines import Heuristic
from canary.env import Env
from canary.eval import run_episode
from canary.social_audit import resolve_text_provider
import scripts.run_v16_social_audit as audit_runner
from scripts.run_v16_social_audit import (
    COMMITTED_PARTIAL_RUNS_ROOT,
    DEFAULT_OUT_JSON,
    DEFAULT_OUT_MD,
    REPO_ROOT,
    _display_path,
    assert_clean_output,
    main,
    offline_execution_guard,
    render_markdown_report,
    resolve_runs_root,
)


def test_resolve_runs_root_ci_fallback_to_committed_partial(tmp_path: Path) -> None:
    assert COMMITTED_PARTIAL_RUNS_ROOT == REPO_ROOT / "results" / "v16_social" / "partial"
    assert COMMITTED_PARTIAL_RUNS_ROOT.is_dir()
    committed_files = sorted(COMMITTED_PARTIAL_RUNS_ROOT.rglob("episodes.jsonl"))
    assert len(committed_files) == 4
    total_committed_records = sum(
        len([ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()])
        for p in committed_files
    )
    assert total_committed_records == 10

    missing_shared = tmp_path / "absent_shared_v16_runs"
    resolved_auto, fell_back_auto = resolve_runs_root("auto", shared_root=missing_shared)
    assert resolved_auto == COMMITTED_PARTIAL_RUNS_ROOT
    assert fell_back_auto is True
    assert _display_path(resolved_auto) == "results/v16_social/partial"

    resolved_explicit_shared, fell_back_shared = resolve_runs_root(
        str(missing_shared),
        shared_root=missing_shared,
    )
    assert resolved_explicit_shared == COMMITTED_PARTIAL_RUNS_ROOT
    assert fell_back_shared is True

    present_shared = tmp_path / "present_shared_v16_runs"
    present_shared.mkdir()
    resolved_present, fell_back_present = resolve_runs_root("auto", shared_root=present_shared)
    assert resolved_present == present_shared
    assert fell_back_present is False

    assert resolve_runs_root(None, shared_root=missing_shared) == (None, False)
    custom_dir = tmp_path / "custom_runs"
    assert resolve_runs_root(custom_dir, shared_root=missing_shared) == (custom_dir, False)


def test_offline_execution_guard_blocks_live_llm_and_restores_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CANARY_OFFLINE", "0")
    orig_get_client = canary_llm.get_client

    with offline_execution_guard(mode="gemini_cached_fallback", cache_dir=tmp_path / "no_cache") as tel:
        assert canary_llm.get_client is not orig_get_client
        with pytest.raises(RuntimeError, match="forbidden"):
            canary_llm.get_client("gemini:gemini-4-carbon")
        with pytest.raises(RuntimeError, match="forbidden"):
            canary_llm.get_client("openai:gpt-5.5")
        stub_client = canary_llm.get_client("stub")
        assert stub_client is not None
        assert tel["blocked_api_attempts"] == 2
        assert tel["live_api_calls"] == 0

    assert canary_llm.get_client is orig_get_client


def test_cli_end_to_end_fresh_ci_fallback_and_corrupt_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    missing_shared = tmp_path / "no_shared_v16_runs"
    fallback_partial = tmp_path / "partial_fallback"
    monkeypatch.setattr(audit_runner, "SHARED_RUNS_ROOT", missing_shared)
    monkeypatch.setattr(audit_runner, "COMMITTED_PARTIAL_RUNS_ROOT", fallback_partial)

    ctl_ep = asdict(run_episode(Env("medium", 30, text_provider=resolve_text_provider("template")), Heuristic()))
    ctl_ep["meta"] = {"provider": "template", "variant": "v0_v14_control"}
    ctl_dir = fallback_partial / "v0_v14_control" / "medium"
    ctl_dir.mkdir(parents=True)
    bad_unfinished = dict(ctl_ep, seed=31, end_reason="infra_crash")
    (ctl_dir / "episodes.jsonl").write_text(
        "\n".join([
            json.dumps(ctl_ep),
            json.dumps(ctl_ep),
            "{broken_json_line",
            json.dumps(bad_unfinished),
        ]) + "\n",
        encoding="utf-8",
    )

    var_spec = "v16:v1_anchoring_authority_confirmation"
    var_ep = asdict(run_episode(Env("medium", 30, text_provider=resolve_text_provider(var_spec)), Heuristic()))
    var_ep["meta"] = {"provider": var_spec, "variant": "v1_anchoring_authority_confirmation"}
    fake_ep = dict(var_ep, seed=32, meta={**var_ep["meta"], "fake": True})
    var_dir = fallback_partial / "v1_anchoring_authority_confirmation" / "medium"
    var_dir.mkdir(parents=True)
    (var_dir / "episodes.jsonl").write_text(
        "\n".join([json.dumps(var_ep), json.dumps(fake_ep)]) + "\n",
        encoding="utf-8",
    )
    (var_dir / "invalid_attempts.jsonl").write_text(
        "{\"attempt\": 1}\n{\"attempt\": 2}\n",
        encoding="utf-8",
    )

    out_json = tmp_path / "out" / "audit.json"
    out_md = tmp_path / "out" / "audit.md"
    rc = main([
        "--workers",
        "1",
        "--tier",
        "medium",
        "--seeds",
        "30-30",
        "--providers",
        "v16:v1_anchoring_authority_confirmation,v16-gemini-stub:v1_anchoring_authority_confirmation,v16-gemini:v1_anchoring_authority_confirmation",
        "--cache-dir",
        str(tmp_path / "missing_gemini_cache"),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ])
    assert rc == 0
    assert out_json.is_file()
    assert out_md.is_file()

    rep = json.loads(out_json.read_text(encoding="utf-8"))
    assert rep["overall_passed"] is True
    assert rep["live_api_calls"] == 0
    assert rep["blocked_api_attempts"] == 0
    assert rep["n_providers_audited"] == 3
    assert rep["n_providers_passed"] == 3
    assert rep["all_v16_providers_passed"] is True
    assert rep["all_episode_replays_passed"] is True

    tpl_diag = rep["baseline_diagnostics"]["v14_template_baseline"]
    assert tpl_diag["six_fairness_checks"]["non_decoy_anger_clean"]["passed"] is False

    sh = rep["shared_runs_replay_audit"]
    assert sh["exists"] is True
    assert sh["files_discovered"] == 2
    assert sh["valid_episodes_verified"] == 2
    assert sh["skipped_invalid_or_incomplete"] == 3
    assert sh["superseded_duplicates"] == 1
    assert sh["invalid_attempt_log_files"] == 1
    assert sh["invalid_attempt_log_entries"] == 2
    assert sh["total_mismatches"] == 0
    assert len(sh["paired_vs_control"]) == 1
    assert sh["paired_vs_control"][0]["n_paired"] == 1

    md = out_md.read_text(encoding="utf-8")
    assert "\u2014" not in md
    assert "\u2013" not in md
    assert "V1.6 Social Fairness and Offline Replay Audit" in md


def test_workers_guard_and_assert_clean_output_rejects_leaks() -> None:
    assert main(["--workers", "2", "--no-runs-root"]) == 2

    with pytest.raises(ValueError, match="forbidden key"):
        assert_clean_output({"mole": "alice"})
    with pytest.raises(ValueError, match="employee identifier leak"):
        assert_clean_output({"note": "suspect e04 leaked doc"})
    with pytest.raises(ValueError, match="em or en dash"):
        assert_clean_output({"note": "bad \u2014 dash"})
    with pytest.raises(ValueError, match="non-finite float"):
        assert_clean_output({"val": float("nan")})
    with pytest.raises(ValueError, match="secret API key"):
        assert_clean_output({"note": "AIza" + "A" * 24})


def test_committed_social_audit_report_and_markdown_sync() -> None:
    assert DEFAULT_OUT_JSON.is_file()
    assert DEFAULT_OUT_MD.is_file()
    assert DEFAULT_OUT_JSON.stat().st_size < 150_000

    committed_json = json.loads(DEFAULT_OUT_JSON.read_text(encoding="utf-8"))
    assert_clean_output(committed_json)
    assert committed_json["overall_passed"] is True
    assert committed_json["live_api_calls"] == 0
    assert committed_json["blocked_api_attempts"] == 0
    assert committed_json["n_providers_audited"] == 16
    assert committed_json["n_providers_passed"] == 16
    assert committed_json["shared_runs_replay_audit"]["valid_episodes_verified"] == 10
    assert committed_json["shared_runs_replay_audit"]["total_mismatches"] == 0

    committed_md = DEFAULT_OUT_MD.read_text(encoding="utf-8")
    assert "\u2014" not in committed_md
    assert "\u2013" not in committed_md
    assert "gemini-3.5-flash" not in committed_md
    assert "% of solver" not in committed_md.lower()
    assert render_markdown_report(committed_json) + "\n" == committed_md
