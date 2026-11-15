from __future__ import annotations

import ast
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_PRELOADED_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

import scripts.tiebreak_channel_ablation_audit as tcaa

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_channel_ablation_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "channel_ablation" / "channel_ablation_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_channel_ablation.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_script_roots = {"torch", "transformers", "subprocess"}
    forbidden_test_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tcaa.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

        tree = ast.parse(src, filename=str(py_path))
        bad_roots = forbidden_script_roots if py_path == SCRIPT_PATH else forbidden_test_roots
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in bad_roots
                    assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in bad_roots
                assert not node.module.startswith(("canary.solver", "canary.world"))
                if node.module == "canary":
                    imported = {a.name for a in node.names}
                    assert "solver" not in imported
                    assert "world" not in imported

    test_toks = list(tokenize.generate_tokens(io.StringIO(SELF_PATH.read_text(encoding="utf-8")).readline))
    assert not [t for t in test_toks if t.type == tokenize.COMMENT]

    newly_loaded_heavy = {m for m in ("torch", "transformers") if m in sys.modules} - set(_PRELOADED_HEAVY)
    assert newly_loaded_heavy == set()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, checked_list = vts._audit_policy_module_ast(
        "scripts/tiebreak_channel_ablation_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    checked = set(checked_list)
    assert "scripts/tiebreak_channel_ablation_audit.py:MaskedEmpiricalBayesPolicy" in checked
    assert "scripts/tiebreak_channel_ablation_audit.py:MaskedCompactLinearDAggerPolicy" in checked


def test_check_cli_json_mode_and_scientific_invariants(capsys: pytest.CaptureFixture[str]) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tcaa.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_human = tcaa.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < 10.0
    assert "OK: verified" in out_human
    assert "2160 episodes" in out_human

    rc_json = tcaa.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tcaa.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    assert tcaa.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    summary = json.loads(raw_json)
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert md_txt == tcaa.render_markdown_report(summary)
    assert tcaa._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d+\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["episodes_per_condition"] == 90
    assert summary["public_channels"] == list(tcaa.PUBLIC_CHANNELS)

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_rolled_out"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
    assert pe["audited_policies_are_open_weight_llm"] is False

    kl = summary["theoretical_channel_kl"]
    assert kl["canary_3arm_surfaced_exact_kl_nats"] == pytest.approx(math.log(3.0), abs=1e-5)
    assert kl["interview_kl_nats_per_call"] == pytest.approx(0.00477, abs=1e-5)
    assert kl["kl_ratio_planted_exact_canary_vs_interview"] > 170.0
    assert kl["kl_ratio_planted_hard_canary_vs_interview"] > 130.0

    totals = summary["totals"]
    assert totals["policies_audited"] == 2
    assert totals["conditions_per_policy"] == 12
    assert totals["total_episodes"] == 2160
    assert totals["fresh_env_replays_verified"] == 216
    assert totals["pooled_canary_voi_share_of_full"] > 0.94

    for pid in tcaa.POLICY_ORDER:
        pb = summary["policies"][pid]
        assert pb["is_open_weight_llm"] is False
        ranking = pb["loo_voi_ranking"]
        assert ranking[0]["channel"] == "canary_traps"
        assert ranking[0]["voi_share_of_full"] > 0.90
        assert ranking[1]["channel"] == "doc_membership"
        assert ranking[-1]["channel"] == "interviews"

        conds = pb["conditions"]
        full_m = conds["full_all_channels"]["overall"]["mean_score"]
        only_can_m = conds["only_canary_traps"]["overall"]["mean_score"]
        ivh = conds["interviews_heavy_no_canary"]["overall"]
        assert full_m > 0.60
        assert only_can_m / full_m > 0.65
        assert conds["only_access_logs"]["overall"]["mean_score"] == 0.0
        assert conds["only_angry_messages"]["overall"]["mean_score"] == 0.0
        assert conds["only_interviews"]["overall"]["mean_score"] == 0.0
        assert ivh["mean_canaries_planted"] == 0.0
        assert ivh["interview_call_share"] > 0.50
        assert ivh["mean_score"] < 0.02


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/channel_ablation/channel_ablation_summary.json",
        "docs/reports/tiebreak_channel_ablation.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    assert tcaa.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()
    assert tcaa.main(["--check", "--root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    shallow_root = tmp_path / "shallow_detached_ci"
    shutil.copytree(no_git_root, shallow_root)
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("c3ff6c08\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("c3ff6c08\n", encoding="utf-8")
    assert tcaa.main(["--check", "--repo-root", str(shallow_root)]) == 0
    _ = capsys.readouterr()

    forbidden_sib = shallow_root / "results" / "tiebreak" / "channel_ablation" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert tcaa.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = shallow_root / "docs" / "reports" / "tiebreak_channel_ablation.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md + "\nPre-registered seeds 0..29 claim.\n", encoding="utf-8")
    assert tcaa.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "Panel Fix A" in capsys.readouterr().err

    md_copy.write_text(orig_md + "\nBad " + chr(0x2014) + " dash.\n", encoding="utf-8")
    assert tcaa.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = shallow_root / "results" / "tiebreak" / "channel_ablation" / "channel_ablation_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tcaa.main(["--check", "--repo-root", str(shallow_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_channel_filter_unit_mechanics_and_live_paired_spot_reproduction() -> None:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    with pytest.raises(ValueError):
        tcaa.ChannelObservationFilter(enabled_channels=("bogus_channel",))

    flt = tcaa.ChannelObservationFilter(
        enabled_channels=("doc_membership",),
        interview_heavy=True,
    )
    flt.reset_filter(
        [{"name": "interview", "input_schema": {"properties": {"topic": {"enum": ["workload"]}}}}],
        "- actions_per_day: 6\n",
    )
    raw_hist = [
        {"t": 0, "day": 1, "tool": "status", "args": {}, "result": {"ok": True, "data": {"day": 1, "actions_left_today": 6}, "error": None}},
        {"t": 1, "day": 1, "tool": "list_employees", "args": {}, "result": {"ok": True, "data": {"employees": [{"id": "e00"}, {"id": "e01"}]}, "error": None}},
        {"t": 2, "day": 1, "tool": "plant_canary", "args": {"doc_title": "c", "assignment": {"e00": "A"}}, "result": {"ok": True, "data": {"canary_id": "can_1"}, "error": None}},
        {"t": 3, "day": 1, "tool": "list_documents", "args": {}, "result": {"ok": True, "data": {"documents": [{"doc_id": "can_1", "is_canary": True}, {"doc_id": "d_1", "is_canary": False}]}, "error": None}},
        {"t": 4, "day": 1, "tool": "check_leak_feed", "args": {}, "result": {"ok": True, "data": {"items": [{"doc_id": "can_1", "variant": "A"}, {"doc_id": "d_1", "variant": None}]}, "error": None}},
        {"t": 5, "day": 1, "tool": "read_access_logs", "args": {}, "result": {"ok": True, "data": {"logs": [{"emp": "e00"}]}, "error": None}},
        {"t": 6, "day": 1, "tool": "search_messages", "args": {}, "result": {"ok": True, "data": {"messages": [{"id": "m1"}]}, "error": None}},
        {"t": 7, "day": 1, "tool": "interview", "args": {"employee": "e00", "topic": "workload"}, "result": {"ok": True, "data": {"answer": "No comment."}, "error": None}},
    ]
    masked = flt.sync_masked_history(raw_hist)
    assert masked[2].result["data"]["canary_id"] == ""
    assert [d["doc_id"] for d in masked[3].result["data"]["documents"]] == ["d_1"]
    assert [i["doc_id"] for i in masked[4].result["data"]["items"]] == ["d_1"]
    assert masked[5].result["data"]["logs"] == []
    assert masked[6].result["data"]["messages"] == []
    assert masked[7].result["data"]["answer"] == "Everything is routine on my end."
    assert flt.apply_action_override("plant_canary", {"doc_title": "x"}) == (
        "interview",
        {"employee": "e01", "topic": "workload"},
    )

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    provider = TemplateProvider()
    eb_fac, eb_meta = tcaa.load_policy_factory("empirical_bayes", repo_root=REPO_ROOT)
    cd_fac, cd_meta = tcaa.load_policy_factory("compact_linear_dagger", repo_root=REPO_ROOT)
    assert eb_meta["is_open_weight_llm"] is False
    assert cd_meta["is_open_weight_llm"] is False

    spot_cases = (
        ("empirical_bayes", eb_fac, "full_all_channels", True),
        ("empirical_bayes", eb_fac, "loo_no_canary_traps", False),
        ("compact_linear_dagger", cd_fac, "full_all_channels", True),
    )
    with tcaa._fast_compact_dagger_features(), tcaa._scoped_world_secret(tcaa.HELDOUT_WORLD_SECRET):
        for pid, fac, cid, check_replay in spot_cases:
            cspec = tcaa.CONDITION_MAP[cid]
            pol = fac(
                800_000,
                enabled_channels=cspec["enabled_channels"],
                interview_heavy=bool(cspec["interview_heavy"]),
                name=f"{pid}:{cid}",
            )
            ep = run_episode(Env("easy", 800_000, text_provider=provider), pol)
            if check_replay:
                rtp.verify_episode_replay(ep, text_provider=provider)
            first_csv = float(summary["policies"][pid]["conditions"][cid]["episode_scores_csv"].split(",")[0])
            assert round(float(ep.score), 4) == pytest.approx(first_csv, abs=1e-4)
