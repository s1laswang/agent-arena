from __future__ import annotations

import ast
import io
import json
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

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_IMPORT_SOLVER = frozenset(
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
)

import scripts.tiebreak_byzantine_stress_audit as tbsa

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_byzantine_stress_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "byzantine_stress" / "byzantine_stress_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_byzantine_stress.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers", "subprocess"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tbsa.check_python_source_hygiene(py_path, run_tokenize=(py_path == SELF_PATH))
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

    self_toks = list(tokenize.generate_tokens(io.StringIO(SELF_PATH.read_text(encoding="utf-8")).readline))
    assert not [t for t in self_toks if t.type == tokenize.COMMENT]

    self_tree = ast.parse(SELF_PATH.read_text(encoding="utf-8"), filename=str(SELF_PATH))
    for node in ast.walk(self_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_roots
                assert not alias.name.startswith(("canary.solver", "canary.world"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_roots
            assert not node.module.startswith(("canary.solver", "canary.world"))
            if node.module == "canary":
                imported = {a.name for a in node.names}
                assert "solver" not in imported
                assert "world" not in imported

    assert _IMPORT_DELTA_HEAVY == frozenset()
    assert _IMPORT_DELTA_SOLVER == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, _ = vts._audit_policy_module_ast(
        "scripts/tiebreak_byzantine_stress_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []


def test_check_cli_json_mode_and_scientific_invariants(capsys: pytest.CaptureFixture[str]) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tbsa.MAX_SUMMARY_BYTES
    assert len(raw_bytes) < 100 * 1024

    t0 = time.perf_counter()
    rc_human = tbsa.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < 10.0
    assert "OK: verified" in out_human
    assert "1800/1800 replays" in out_human
    assert "16/16 positive CIs" in out_human

    rc_json = tbsa.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tbsa.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    assert tbsa.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii()
    assert md_txt.isascii()

    summary = json.loads(raw_json)
    assert md_txt == tbsa.render_markdown_report(summary)
    assert tbsa._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d{6,}\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["episodes_per_cell"] == 90
    assert summary["episodes_per_policy"] == 360
    assert summary["dropout_rates"] == [0.0, 0.15, 0.3, 0.5]
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["compact_policies_are_open_weight_llm"] is False
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"

    totals = summary["totals"]
    assert totals["trained_policies_audited"] == 4
    assert totals["baseline_policies_audited"] == 1
    assert totals["perturbation_levels_audited"] == 4
    assert totals["trained_cells_total"] == 16
    assert totals["trained_cells_positive_ci95_vs_abstain"] == 16
    assert totals["trained_cells_positive_ci95_vs_heuristic"] == 16
    assert totals["trained_episodes_evaluated"] == 1440
    assert totals["total_episodes_evaluated"] == 1800
    assert totals["fresh_env_replays_verified"] == 1800
    assert totals["clean_parity_episodes_verified"] == 450

    drop_keys = ("0.00", "0.15", "0.30", "0.50")
    for pid in tbsa.TRAINED_POLICY_ORDER:
        pb = summary["policies"][pid]
        assert pb["is_open_weight_llm"] is False
        assert pb["trained"] is True
        assert pb["calibrated_ev_stopping"] is True
        assert pb["replay_verified"] is True
        assert pb["invalid_episodes"] == 0
        assert pb["clean_parity_verified_episodes"] == 90

        masked_curve: list[float] = []
        flip_curve: list[float] = []
        for dkey in drop_keys:
            cb = pb["by_dropout"][dkey]
            ov = cb["overall"]
            pa = cb["paired_vs_abstain"]
            ph = cb["paired_vs_heuristic"]
            assert ov["valid_call_rate"] == 1.0
            assert pa["ci95_low"] > 0.0
            assert pa["public_ev_ci95_low"] > 0.0
            assert ph["ci95_low"] > 0.0
            assert ph["public_ev_ci95_low"] > 0.0
            masked_curve.append(float(ov["mean_masked_events"]))
            flip_curve.append(float(ov["mean_byzantine_flips"]))

        assert masked_curve[0] == 0.0
        assert flip_curve[0] == 0.0
        assert masked_curve[0] < masked_curve[1] < masked_curve[2] < masked_curve[3]
        assert flip_curve[0] < flip_curve[1] < flip_curve[2] < flip_curve[3]

        gd = pb["graceful_degradation"]
        assert gd["abstain_shift_000_to_050"] > 0.0
        assert gd["stress_050_wrong_rate"] < 0.06
        assert gd["stress_050_score"] > 0.40
        assert gd["positive_ci95_vs_abstain_levels"] == 4
        assert gd["positive_ci95_vs_heuristic_levels"] == 4

    heur = summary["policies"][tbsa.BASELINE_POLICY_ID]
    assert heur["is_open_weight_llm"] is False
    assert heur["trained"] is False
    assert heur["calibrated_ev_stopping"] is False
    heur_scores = [float(heur["by_dropout"][k]["overall"]["mean_score"]) for k in drop_keys]
    assert heur_scores[0] > heur_scores[1] > heur_scores[2] > heur_scores[3]
    for dkey in drop_keys:
        assert heur["by_dropout"][dkey]["overall"]["abstain_rate"] == 0.0
    heur_050 = heur["by_dropout"]["0.50"]["overall"]
    assert heur_050["mean_score"] < -0.15
    assert heur_050["ci95_high"] < 0.0
    assert heur_050["wrong_accuse_rate"] > 0.45
    assert heur_050["sub_breakeven_accuse_rate"] > 0.50


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/byzantine_stress/byzantine_stress_summary.json",
        "docs/reports/tiebreak_byzantine_stress.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    t0 = time.perf_counter()
    assert tbsa.main(["--check", "--repo-root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t0) < 10.0
    _ = capsys.readouterr()

    (no_git_root / ".git").mkdir()
    (no_git_root / ".git" / "shallow").write_text("47888e4f\n", encoding="utf-8")
    (no_git_root / ".git" / "HEAD").write_text("47888e4f\n", encoding="utf-8")
    t1 = time.perf_counter()
    assert tbsa.main(["--check", "--root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t1) < 10.0
    _ = capsys.readouterr()

    forbidden_sib = no_git_root / "results" / "tiebreak" / "byzantine_stress" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert tbsa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = no_git_root / "docs" / "reports" / "tiebreak_byzantine_stress.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(
        orig_md + "\nPre-registered seeds 0..29 claim.\nBad " + chr(0x2014) + " dash.\n",
        encoding="utf-8",
    )
    assert tbsa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_md = capsys.readouterr().err
    assert "Panel Fix A" in err_md
    assert "em dash" in err_md
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = no_git_root / "results" / "tiebreak" / "byzantine_stress" / "byzantine_stress_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tbsa.main(["--check", "--repo-root", str(no_git_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_byzantine_stream_idempotence_and_live_paired_spot_reproduction() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    from canary.types import Step
    import scripts.run_tiebreak_policy as rtp

    raw_steps = [
        Step(0, 1, "list_employees", {}, {"ok": True, "data": {"employees": [{"id": "e00"}, {"id": "e01"}, {"id": "e02"}]}, "error": None}),
        Step(1, 1, "read_access_logs", {}, {"ok": True, "data": {"logs": [{"day": 1, "employee": "e00", "doc_id": "d1", "after_hours": False}]}, "error": None}),
        Step(2, 1, "search_messages", {}, {"ok": True, "data": {"messages": [{"id": "m1", "sender": "e00", "body": "angry"}]}, "error": None}),
        Step(3, 1, "read_message", {"id": "m1"}, {"ok": True, "data": {"message": {"id": "m1", "sender": "e00", "subject": "s", "body": "b", "snippet": "sn"}}, "error": None}),
        Step(4, 1, "interview", {"employee": "e00", "topic": "workload"}, {"ok": True, "data": {"employee": "e00", "topic": "workload", "answer": "Was evasive and vague."}, "error": None}),
        Step(5, 1, "check_leak_feed", {}, {"ok": True, "data": {"items": [{"doc_id": "can_1", "variant": "A"}]}, "error": None}),
    ]

    clean_stream = tbsa.ByzantineObservationStream("easy", 800_000, 0.00)
    clean_out = clean_stream.transform_history(raw_steps)
    assert clean_stream.masked_events == 0
    assert clean_stream.byzantine_flips == 0
    assert [s.result for s in clean_out] == [s.result for s in raw_steps]

    full_drop = tbsa.ByzantineObservationStream("easy", 800_000, 1.00)
    dropped_out = full_drop.transform_history(raw_steps)
    assert full_drop.masked_events == 5
    assert dropped_out[1].result["data"]["logs"] == []
    assert dropped_out[2].result["data"]["messages"] == []
    assert dropped_out[3].result["data"]["message"]["body"] == ""
    assert dropped_out[4].result["data"]["answer"] == ""
    assert dropped_out[5].result["data"]["items"][0]["variant"] is None

    s_a = tbsa.ByzantineObservationStream("medium", 800_007, 0.50)
    s_b = tbsa.ByzantineObservationStream("medium", 800_007, 0.50)
    for i in range(1, len(raw_steps) + 1):
        out_a = s_a.transform_history(raw_steps[:i])
    out_b = s_b.transform_history(raw_steps)
    assert [x.result for x in out_a] == [x.result for x in out_b]
    assert (s_a.masked_events, s_a.byzantine_flips) == (s_b.masked_events, s_b.byzantine_flips)

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    provider = TemplateProvider()
    eb_opt = tbsa.load_eb_observer_params(REPO_ROOT)
    eb_fac, eb_meta = tbsa.load_single_policy_factory("empirical_bayes", repo_root=REPO_ROOT)
    heur_fac, heur_meta = tbsa.load_single_policy_factory(tbsa.BASELINE_POLICY_ID, repo_root=REPO_ROOT)
    assert eb_meta["trained"] is True
    assert heur_meta["trained"] is False

    spot_cases = (
        ("empirical_bayes", eb_fac, "0.00", 0.00, True),
        ("empirical_bayes", eb_fac, "0.50", 0.50, True),
        (tbsa.BASELINE_POLICY_ID, heur_fac, "0.50", 0.50, False),
    )

    with tbsa._scoped_world_secret(tbsa.HELDOUT_WORLD_SECRET):
        for pid, fac, dkey, drate, do_replay in spot_cases:
            env = Env("easy", 800_000, text_provider=provider)
            spec = env.tools_spec()
            instr = env.instruction()
            stream = tbsa.ByzantineObservationStream("easy", 800_000, drate)
            ep, pstats = tbsa.run_perturbed_episode(env, fac(800_000), stream)
            if do_replay:
                rtp.verify_episode_replay(ep, text_provider=provider)
            if dkey == "0.00":
                ep_ref = run_episode(Env("easy", 800_000, text_provider=provider), fac(800_000))
                assert tbsa._canonical_ep_sha(ep) == tbsa._canonical_ep_sha(ep_ref)
            ev, _, _, _, _ = tbsa.compute_calibrated_public_ev(ep, spec, instr, eb_opt)
            exp_spot = summary["policies"][pid]["by_dropout"][dkey]["spot_easy_800000"]
            assert round(float(ep.score), 5) == pytest.approx(exp_spot["score"], abs=1e-5)
            assert round(float(ev), 5) == pytest.approx(exp_spot["public_ev"], abs=1e-5)
            assert pstats["masked_events"] == exp_spot["masked_events"]
            assert pstats["byzantine_flips"] == exp_spot["byzantine_flips"]

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - fn_solver
    ) == set()
