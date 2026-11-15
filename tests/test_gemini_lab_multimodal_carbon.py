from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import shutil
import tokenize

import pytest

from canary.gemini import multimodal_carbon as MC

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "canary" / "gemini" / "multimodal_carbon.py"
LIVE_ROLE_DIR = REPO_ROOT / "results" / "gemini" / "roles_carbon" / "multimodal_evidence"
LIVE_INDEX_PATH = LIVE_ROLE_DIR / "index.json"
LIVE_DOC_PATH = REPO_ROOT / "docs" / "gemini" / "roles_carbon" / "multimodal_evidence.md"

EXPECTED_17_RUNS = (
    "access-heatmap-carbon",
    "access-heatmap-hard-carbon",
    "access-heatmap-v14-high-s8to11-carbon",
    "access-heatmap-v14-low-s8to11-carbon",
    "access-heatmap-v14-sweep-carbon",
    "belief-chart-forensics-carbon",
    "carbon-trajectory-forensics",
    "carbon-trajectory-forensics-v14-expanded",
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds10to14-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "multi-image-dossier-carbon",
    "multi-image-dossier-med6to8-hard5to7-carbon",
    "multi-image-dossier-v14-expanded-carbon",
    "scanned-evidence-ablation-carbon",
)

SAMPLE_FOUR_RUNS = (
    "memo-watermark-ablation-carbon",
    "access-heatmap-carbon",
    "multi-image-dossier-carbon",
    "belief-chart-forensics-carbon",
)

FORBIDDEN_IMPORT_PREFIXES = (
    "google",
    "genai",
    "openai",
    "anthropic",
    "requests",
    "httpx",
    "urllib",
    "http",
    "socket",
    "aiohttp",
)


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")


def _stage_sandbox(tmp_path: Path, run_names: tuple[str, ...] = SAMPLE_FOUR_RUNS) -> tuple[Path, Path, Path]:
    role_dir = tmp_path / "results" / "gemini" / "roles_carbon" / "multimodal_evidence"
    role_dir.mkdir(parents=True, exist_ok=True)
    for name in run_names:
        shutil.copytree(LIVE_ROLE_DIR / name, role_dir / name)
    index_path = role_dir / "index.json"
    doc_path = tmp_path / "docs" / "gemini" / "roles_carbon" / "multimodal_evidence.md"
    return tmp_path, index_path, doc_path


def test_live_17_runs_discovered_and_index_not_confused_as_run() -> None:
    assert LIVE_INDEX_PATH.is_file()
    runs, hygiene_issues = MC.discover_multimodal_runs(LIVE_ROLE_DIR, root=REPO_ROOT)
    assert hygiene_issues == []
    assert [r["run_id"] for r in runs] == list(EXPECTED_17_RUNS)
    assert len(runs) == 17
    assert all(r["verified"] is True for r in runs)
    assert all(r["stub"] is False for r in runs)
    assert all(r["model_id"] == "gemini-4-carbon" for r in runs)


def test_live_suite_exact_totals_and_pricing_reconciliation() -> None:
    payload = json.loads(LIVE_INDEX_PATH.read_text(encoding="utf-8"))
    assert payload["role"] == "multimodal_evidence"
    assert payload["target_model"] == "gemini-4-carbon"
    assert payload["verified"] is True

    totals = payload["totals"]
    assert totals["run_count"] == 17
    assert totals["scanned_run_count"] == 17
    assert totals["rejected_run_count"] == 0
    assert totals["subfamily_count"] == 4
    assert totals["images_read_by_model"] == 260
    assert totals["image_bytes_verified"] == 27268097

    usage = totals["usage"]
    assert usage["calls"] == 226
    assert usage["in"] == 486594
    assert usage["out"] == 47941
    assert usage["thinking"] == 206845
    assert usage["cached"] == 0
    assert usage["cost_usd"] == pytest.approx(3.521048, abs=1e-9)
    assert payload["hygiene"]["pricing_reconciled_all_runs"] is True


def test_live_hygiene_zero_secrets_zero_judge_seeds_zero_world_keys() -> None:
    payload = json.loads(LIVE_INDEX_PATH.read_text(encoding="utf-8"))
    hyg = payload["hygiene"]
    assert hyg["secret_hygiene_clean"] is True
    assert hyg["secret_leak_count"] == 0
    assert hyg["judge_seed_count"] == 0
    assert hyg["world_answer_key_file_count"] == 0
    assert hyg["observed_dev_seeds"] == list(range(15))
    assert hyg["max_observed_seed"] == 14
    assert hyg["root_hygiene_issues"] == []


def test_check_cli_idempotent_and_non_mutating(capsys: pytest.CaptureFixture[str]) -> None:
    idx_before = LIVE_INDEX_PATH.read_bytes()
    doc_before = LIVE_DOC_PATH.read_bytes()

    rc_plain = MC.main(["--check"])
    out_plain = capsys.readouterr().out
    assert rc_plain == 0
    assert "multimodal_carbon [OK]" in out_plain

    rc_json = MC.main(["--check", "--json"])
    out_json = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert out_json["ok"] is True
    assert out_json["index_in_sync"] is True
    assert out_json["doc_in_sync"] is True
    assert out_json["errors"] == []

    assert LIVE_INDEX_PATH.read_bytes() == idx_before
    assert LIVE_DOC_PATH.read_bytes() == doc_before


def test_sync_into_tmp_path_matches_committed_byte_for_byte(tmp_path: Path) -> None:
    sandbox_root, idx_path, doc_path = _stage_sandbox(tmp_path, EXPECTED_17_RUNS)
    rc_sync = MC.main(["--root", str(sandbox_root), "--sync"])
    assert rc_sync == 0
    assert idx_path.read_bytes() == LIVE_INDEX_PATH.read_bytes()
    assert doc_path.read_bytes() == LIVE_DOC_PATH.read_bytes()
    assert MC.main(["--root", str(sandbox_root), "--check"]) == 0


def test_subfamily_1_watermark_memo_ablation_metrics() -> None:
    payload = json.loads(LIVE_INDEX_PATH.read_text(encoding="utf-8"))
    wm = payload["subfamilies"]["watermark_memo_ablation"]
    assert wm["run_count"] == 6
    assert wm["images_read"] == 156
    assert wm["batch_episodes_total"] == 30
    assert wm["unique_paired_episodes"] == 27
    assert wm["batch_scans_exact"] == 156
    assert wm["batch_scans_total"] == 156
    assert wm["batch_canary_scans_exact"] == 49
    assert wm["batch_canary_scans_total"] == 49
    assert wm["ocr_watermark_accuracy"] == 1.0
    assert wm["oracle_recovery_ratio"] == 1.0

    med = wm["by_tier"]["medium"]
    assert med["n_unique_episodes"] == 12
    assert med["scans_exact_matches"] == 58 and med["scans_inspected"] == 58
    assert med["multimodal_mean_score"] == pytest.approx(0.7358, abs=1e-4)
    assert med["blind_mean_score"] == pytest.approx(0.0, abs=1e-4)
    assert med["multimodal_accuracy"] == 1.0
    assert med["blind_accuracy"] == 0.0

    hard = wm["by_tier"]["hard"]
    assert hard["n_unique_episodes"] == 15
    assert hard["scans_exact_matches"] == 82 and hard["scans_inspected"] == 82
    assert hard["multimodal_mean_score"] == pytest.approx(0.5387, abs=1e-4)
    assert hard["blind_mean_score"] == pytest.approx(0.3280, abs=1e-4)
    assert hard["paired_score_delta"] == pytest.approx(0.2107, abs=1e-4)

    ov = wm["by_tier"]["overall"]
    assert ov["n_unique_episodes"] == 27
    assert ov["scans_exact_matches"] == 140 and ov["scans_inspected"] == 140
    assert ov["canary_scans_exact_matches"] == 45 and ov["canary_scans_inspected"] == 45
    assert ov["multimodal_mean_score"] == pytest.approx(0.6263, abs=1e-4)
    assert ov["blind_mean_score"] == pytest.approx(0.1822, abs=1e-4)
    assert ov["paired_score_delta"] == pytest.approx(0.4441, abs=1e-4)
    assert ov["multimodal_accuracy"] == 1.0
    assert ov["blind_accuracy"] == pytest.approx(0.3704, abs=1e-4)


def test_subfamily_2_soc_access_heatmap_and_thinking_calibration() -> None:
    payload = json.loads(LIVE_INDEX_PATH.read_text(encoding="utf-8"))
    soc = payload["subfamilies"]["soc_access_heatmap_vision"]
    assert soc["run_count"] == 5
    assert soc["images_read"] == 28
    assert soc["total_world_evaluations"] == 28
    assert soc["unique_worlds"] == 22

    pooled = soc["pooled_all_evaluations"]
    assert pooled["top1_mole_hits"] == 27 and pooled["n"] == 28
    assert pooled["top3_mole_hits"] == 28
    assert pooled["top1_decoy_hits"] == 28
    assert pooled["avoided_framing_trap_hits"] == 28
    assert pooled["naive_mole_hits"] == 0
    assert pooled["naive_trapped_by_decoy_hits"] == 28

    uniq = soc["deduplicated_unique_worlds"]
    assert uniq["top1_mole_hits"] == 21 and uniq["n"] == 22
    assert uniq["top1_decoy_hits"] == 22

    cal_all = soc["thinking_level_calibration"]["all_paired_worlds"]
    assert cal_all["n_paired_worlds"] == 6
    assert cal_all["low"]["mean_brier_score"] == pytest.approx(0.002117, abs=1e-6)
    assert cal_all["high"]["mean_brier_score"] == pytest.approx(0.000254, abs=1e-6)
    assert cal_all["low"]["thinking_tokens"] == 1983
    assert cal_all["high"]["thinking_tokens"] == 85629
    assert cal_all["brier_delta_high_minus_low"] < 0.0

    cal_hard = soc["thinking_level_calibration"]["hard_seeds_8to11"]
    assert cal_hard["n_paired_worlds"] == 4
    assert cal_hard["worlds"] == ["hard:8", "hard:9", "hard:10", "hard:11"]
    assert cal_hard["low"]["top1_mole_accuracy"] == 1.0
    assert cal_hard["high"]["top1_mole_accuracy"] == 1.0
    assert cal_hard["low"]["mean_brier_score"] == pytest.approx(0.003125, abs=1e-6)
    assert cal_hard["high"]["mean_brier_score"] == pytest.approx(0.000331, abs=2e-6)
    assert cal_hard["low"]["thinking_tokens"] == 1688
    assert cal_hard["high"]["thinking_tokens"] == 60977


def test_subfamily_3_multi_image_incident_dossier_fusion() -> None:
    payload = json.loads(LIVE_INDEX_PATH.read_text(encoding="utf-8"))
    dos = payload["subfamilies"]["multi_image_incident_dossier"]
    assert dos["run_count"] == 3
    assert dos["images_per_call"] == 3
    assert dos["images_read"] == 51
    assert dos["unique_worlds"] == 17
    assert dos["usage"]["calls"] == 17

    ov = dos["by_tier"]["overall"]
    assert ov["n_worlds"] == 17
    assert ov["top1_mole_hits"] == 14
    assert ov["top3_mole_hits"] == 16
    assert ov["top1_decoy_hits"] == 16
    assert ov["decoy_identified_hits"] == 17
    assert ov["avoided_framing_trap_hits"] == 17
    assert ov["memo_scans_matched"] == 43 and ov["memo_scans_total"] == 43
    assert ov["memo_scan_readout_accuracy"] == 1.0
    assert ov["suspect_dept_hits"] == 15
    assert ov["image1_only_mole_accuracy"] == 0.0
    assert ov["image2_only_mole_accuracy"] == 0.0
    assert ov["image3_only_mole_accuracy"] == 0.0


def test_subfamily_4_visual_chart_forensics_and_clusters() -> None:
    payload = json.loads(LIVE_INDEX_PATH.read_text(encoding="utf-8"))
    ch = payload["subfamilies"]["visual_chart_forensics"]
    assert ch["run_count"] == 3
    assert ch["images_read"] == 25
    assert ch["total_charts_evaluated"] == 25
    assert ch["unique_source_episodes"] == 20

    pooled = ch["pooled_all_charts"]
    assert pooled["ev_threshold_hits"] == 25
    assert pooled["stop_day_exact_hits"] == 25
    assert pooled["hidden_bleed_gap_hits"] == 25
    assert pooled["v14_entropy_lag_hits"] == 19 and pooled["v14_entropy_lag_total"] == 19
    assert pooled["v14_outcome_pattern_hits"] == 19 and pooled["v14_outcome_pattern_total"] == 19
    assert pooled["cluster_diagnoses"] == {
        "fooled_wrong_suspect": 2,
        "horizon_below_ev_stall": 4,
        "horizon_forced_guess": 2,
        "none_justified_accusation": 16,
        "premature_early_accusation": 1,
    }

    uniq = ch["deduplicated_unique_episodes"]
    assert uniq["n_charts"] == 20
    assert sum(uniq["cluster_diagnoses"].values()) == 20


def test_markdown_doc_structure_scope_and_tables() -> None:
    md = LIVE_DOC_PATH.read_text(encoding="utf-8")
    assert "non_judged_multimodal_research_and_arena_probes_dev_seeds_only" in md
    assert "a8f99c2537c91d72" in md
    assert "docs/gemini/validation.md" in md
    assert "Suite Totals" in md
    assert "4 Multimodal Sub-Families Summary" in md
    assert "17-Run Provenance Ledger" in md
    assert "$3.521048" in md
    for name in EXPECTED_17_RUNS:
        assert f"`{name}`" in md
    for idx in range(1, 18):
        assert f"{chr(35) * 3} {idx}. `" in md


def test_tamper_rejects_stub_true_in_tmp_path(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 0

    meta_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon" / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["stub"] = True
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="stub_or_synthetic_run"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 1
    assert MC.main(["--root", str(sandbox_root), "--check"]) == 1


@pytest.mark.parametrize("bad_flag", ["fake_env", "smoke", "synthetic"])
def test_tamper_rejects_smoke_fake_env_and_synthetic_flags(tmp_path: Path, bad_flag: str) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    meta_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon" / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta[bad_flag] = True
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 1


def test_tamper_rejects_non_carbon_model_id(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    meta_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "memo-watermark-ablation-carbon" / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["model_id"] = "gemini-2.5-flash"
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="wrong_model:gemini-2.5-flash"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 1


def test_tamper_rejects_companion_wrong_model(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    res_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "multi-image-dossier-carbon" / "results.json"
    res = json.loads(res_p.read_text(encoding="utf-8"))
    res["model_id"] = "gemini-2.5-pro"
    res_p.write_text(json.dumps(res, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="companion_wrong_model"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)


def test_tamper_rejects_invalid_commit_sha(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    meta_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "belief-chart-forensics-carbon" / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["commit"] = "not_a_valid_hex_sha"
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid_commit"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)


def test_tamper_rejects_zero_calls_and_pricing_mismatch(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    meta_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon" / "meta.json"
    orig = json.loads(meta_p.read_text(encoding="utf-8"))

    bad_cost = json.loads(json.dumps(orig))
    bad_cost["usage"]["cost_usd"] = 9.999999
    meta_p.write_text(json.dumps(bad_cost, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="cost_mismatch_vs_pricing"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)

    bad_calls = json.loads(json.dumps(orig))
    bad_calls["usage"]["calls"] = 0
    meta_p.write_text(json.dumps(bad_calls, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="non_positive_calls"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)


def test_tamper_rejects_google_api_key_leak(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    sum_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon" / "summary.md"
    fake_gkey = "AI" + "za" + "FakeFixtureTestValue1234567890"
    sum_p.write_text(sum_p.read_text(encoding="utf-8") + f"\nleaked={fake_gkey}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="secret_hygiene_violation"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 1


def test_tamper_rejects_sk_and_oauth_secret_leaks(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    sum_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "belief-chart-forensics-carbon" / "summary.md"
    base_txt = sum_p.read_text(encoding="utf-8")

    fake_sk = "s" + "k-FakeFixtureTestValue1234567890"
    sum_p.write_text(base_txt + f"\n{fake_sk}\n", encoding="utf-8")
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 1

    fake_oauth = "ya29" + ".FakeFixtureTestValue1234567890"
    sum_p.write_text(base_txt + f"\n{fake_oauth}\n", encoding="utf-8")
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 1


def test_tamper_rejects_judge_seed_900000_in_meta_and_companion(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    meta_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon" / "meta.json"
    orig_meta = meta_p.read_text(encoding="utf-8")
    meta = json.loads(orig_meta)
    meta["seeds"] = [0, 1, 900000]
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="judge_seed_violation:900000"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)

    meta_p.write_text(orig_meta, encoding="utf-8")
    diag_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "belief-chart-forensics-carbon" / "diagnoses.json"
    diags = json.loads(diag_p.read_text(encoding="utf-8"))
    diags[0]["source_episode"]["seed"] = 900042
    diag_p.write_text(json.dumps(diags, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="judge_seed_violation:900042"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)


def test_tamper_rejects_world_json_answer_key_files(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    world_in_run = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon" / "0.world.json"
    world_in_run.write_text(json.dumps({"tier": "medium", "mole": "e05"}), encoding="utf-8")

    with pytest.raises(ValueError, match="world_answer_key_file"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)

    world_in_run.unlink()
    worlds_dir = sandbox_root / "data" / "worlds"
    worlds_dir.mkdir(parents=True, exist_ok=True)
    (worlds_dir / "900000.world.json").write_text(json.dumps({"tier": "hard", "mole": "e11"}), encoding="utf-8")

    with pytest.raises(ValueError, match="world_answer_key_file"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)


def test_tamper_rejects_out_of_sync_multimodal_evidence_md(tmp_path: Path) -> None:
    sandbox_root, _, doc_path = _stage_sandbox(tmp_path)
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 0
    assert MC.main(["--root", str(sandbox_root), "--check"]) == 0

    tampered = doc_path.read_text(encoding="utf-8") + "\nstale manual edit\n"
    doc_path.write_text(tampered, encoding="utf-8")

    report = MC.check_multimodal_carbon(root=sandbox_root)
    assert report["ok"] is False
    assert report["doc_in_sync"] is False
    assert any("out_of_sync_doc_md" in e for e in report["errors"])
    assert MC.main(["--root", str(sandbox_root), "--check"]) == 1
    assert doc_path.read_text(encoding="utf-8") == tampered

    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 0
    assert MC.main(["--root", str(sandbox_root), "--check"]) == 0


def test_tamper_rejects_out_of_sync_or_missing_index_json(tmp_path: Path) -> None:
    sandbox_root, idx_path, _ = _stage_sandbox(tmp_path)
    assert MC.main(["--root", str(sandbox_root), "--sync"]) == 0

    idx_path.write_text("{\"stale\": true}\n", encoding="utf-8")
    assert MC.main(["--root", str(sandbox_root), "--check"]) == 1

    idx_path.unlink()
    report = MC.check_multimodal_carbon(root=sandbox_root)
    assert report["ok"] is False
    assert any("missing_index_json" in e for e in report["errors"])


def test_tamper_rejects_image_manifest_mismatch_and_committed_png(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    run_dir = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon"
    stray_png = run_dir / "stray.png"
    stray_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="forbidden_committed_file"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)
    stray_png.unlink()

    meta_p = run_dir / "meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    meta["image_manifest"]["total_bytes"] += 1
    meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest_bytes_sum_mismatch"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)


def test_tamper_rejects_forbidden_dash_in_run_artifact(tmp_path: Path) -> None:
    sandbox_root, _, _ = _stage_sandbox(tmp_path)
    sum_p = sandbox_root / MC.DEFAULT_ROLE_DIR / "access-heatmap-carbon" / "summary.md"
    sum_p.write_text(sum_p.read_text(encoding="utf-8") + f"\nbad {chr(0x2014)} dash\n", encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden_dash"):
        MC.consolidate_multimodal_carbon(root=sandbox_root, strict=True)


def test_source_hygiene_multimodal_carbon_zero_comments_dashes_or_network_imports() -> None:
    src = MODULE_PATH.read_text(encoding="utf-8")
    for dash in MC.FORBIDDEN_DASHES:
        assert dash not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert chr(35) not in src
    assert MC.scan_text_secrets(src) == []

    tree = ast.parse(src)
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)
    for mod_name in imported_names:
        top = mod_name.split(".")[0]
        assert top not in FORBIDDEN_IMPORT_PREFIXES, f"forbidden network/SDK import: {mod_name}"


def test_source_hygiene_this_test_file_zero_comments_dashes_or_secrets() -> None:
    self_src = Path(__file__).resolve().read_text(encoding="utf-8")
    for dash in MC.FORBIDDEN_DASHES:
        assert dash not in self_src
    tokens = list(tokenize.generate_tokens(io.StringIO(self_src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert chr(35) not in self_src
    assert MC.scan_text_secrets(self_src) == []


def test_generated_outputs_have_zero_forbidden_dashes_or_secrets() -> None:
    idx_txt = LIVE_INDEX_PATH.read_text(encoding="utf-8")
    doc_txt = LIVE_DOC_PATH.read_text(encoding="utf-8")
    for dash in MC.FORBIDDEN_DASHES:
        assert dash not in idx_txt
        assert dash not in doc_txt
    assert MC.scan_text_secrets(idx_txt) == []
    assert MC.scan_text_secrets(doc_txt) == []
    json.loads(idx_txt)
    assert len(doc_txt) > 2000
