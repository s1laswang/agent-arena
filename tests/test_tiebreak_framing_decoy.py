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

import scripts.tiebreak_framing_decoy_audit as tfda

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_framing_decoy_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "framing_decoy" / "framing_decoy_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_framing_decoy.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_ast_policy_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers", "subprocess"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tfda.check_python_source_hygiene(py_path, run_tokenize=True)
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

    ast_errs, checked_classes = vts._audit_policy_module_ast(
        "scripts/tiebreak_framing_decoy_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    assert "scripts/tiebreak_framing_decoy_audit.py:FramingGullibleHeuristicPolicy" in checked_classes


def test_check_cli_json_mode_and_scientific_invariants(capsys: pytest.CaptureFixture[str]) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tfda.MAX_SUMMARY_BYTES
    assert len(raw_bytes) < 75 * 1024

    t0 = time.perf_counter()
    rc_human = tfda.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < 10.0
    assert "OK: verified" in out_human
    assert "450/450 replays" in out_human
    assert "4/4 positive CIs" in out_human

    rc_json = tfda.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tfda.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    assert tfda.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii()
    assert md_txt.isascii()

    summary = json.loads(raw_json)
    assert md_txt == tfda.render_markdown_report(summary)
    assert tfda._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d{6,}\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["episodes_per_policy"] == 90
    assert summary["medium_hard_episodes_per_policy"] == 60
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
    assert totals["total_episodes_evaluated"] == 450
    assert totals["fresh_env_replays_verified"] == 450
    assert totals["trained_positive_ci95_vs_gullible"] == 4
    assert totals["trained_positive_ci95_vs_do_nothing"] == 4

    eb_diag = summary["eb_likelihood_diagnostics"]
    assert eb_diag["param_count"] == 11
    assert eb_diag["w_angry_msg"] < -2.0
    assert eb_diag["angry_msg_sign"] == "negative_exonerating"
    assert eb_diag["canary_split_contrast_nats"] > 5.0
    assert eb_diag["canary_vs_after_hours_weight_ratio"] > 40.0

    gul = summary["policies"][tfda.BASELINE_POLICY_ID]
    assert gul["trained"] is False
    assert gul["is_open_weight_llm"] is False
    assert gul["overall"]["mean_score"] < -0.75
    assert gul["overall"]["wrong_accuse_rate"] >= 0.85
    assert gul["overall"]["trap_false_accuse_rate"] >= 0.85
    assert gul["medium_hard_traps"]["decoy_false_accuse_rate"] >= 0.90

    for pid in tfda.TRAINED_POLICY_ORDER:
        pb = summary["policies"][pid]
        assert pb["trained"] is True
        assert pb["is_open_weight_llm"] is False
        assert pb["replay_verified"] is True
        assert pb["invalid_episodes"] == 0
        assert pb["overall"]["valid_call_rate"] == 1.0
        assert pb["overall"]["mean_canaries_planted"] > 5.0
        assert pb["paired_vs_gullible"]["ci95_low"] > 1.20
        assert pb["paired_vs_do_nothing"]["ci95_low"] > 0.50

    eb = summary["policies"]["empirical_bayes"]
    assert eb["overall"]["wrong_accuse_rate"] <= 0.02
    assert eb["overall"]["trap_false_accuse_rate"] <= 0.02
    assert eb["medium_hard_traps"]["decoy_false_accuse_rate"] == 0.0
    assert eb["medium_hard_traps"]["framed_log_false_accuse_rate"] == 0.0


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/framing_decoy/framing_decoy_summary.json",
        "docs/reports/tiebreak_framing_decoy.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    t0 = time.perf_counter()
    assert tfda.main(["--check", "--repo-root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t0) < 10.0
    _ = capsys.readouterr()

    (no_git_root / ".git").mkdir()
    (no_git_root / ".git" / "shallow").write_text("c445a4ca\n", encoding="utf-8")
    (no_git_root / ".git" / "HEAD").write_text("c445a4ca\n", encoding="utf-8")
    t1 = time.perf_counter()
    assert tfda.main(["--check", "--root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t1) < 10.0
    _ = capsys.readouterr()

    forbidden_sib = no_git_root / "results" / "tiebreak" / "framing_decoy" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert tfda.main(["--check", "--repo-root", str(no_git_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = no_git_root / "docs" / "reports" / "tiebreak_framing_decoy.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(
        orig_md + "\nPre-registered seeds 0..29 claim.\nBad " + chr(0x2014) + " dash.\n",
        encoding="utf-8",
    )
    assert tfda.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_md = capsys.readouterr().err
    assert "Panel Fix A" in err_md
    assert "em dash" in err_md
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = no_git_root / "results" / "tiebreak" / "framing_decoy" / "framing_decoy_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_val"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tfda.main(["--check", "--repo-root", str(no_git_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_live_paired_spot_reproduction_and_replay_parity() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    t0 = time.perf_counter()
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    provider = TemplateProvider()
    gul_fac, gul_meta = tfda.load_single_policy_factory(tfda.BASELINE_POLICY_ID, repo_root=REPO_ROOT)
    eb_fac, eb_meta = tfda.load_single_policy_factory("empirical_bayes", repo_root=REPO_ROOT)
    assert gul_meta["trained"] is False
    assert eb_meta["trained"] is True

    with tfda._scoped_world_secret(tfda.HELDOUT_WORLD_SECRET):
        for tier in ("medium", "hard"):
            trap_info = tfda.profile_public_trap_suspects(tier, 800_000, provider)
            assert len(trap_info["angry_suspects"]) >= 1
            for pid, fac in ((tfda.BASELINE_POLICY_ID, gul_fac), ("empirical_bayes", eb_fac)):
                ep = run_episode(Env(tier, 800_000, text_provider=provider), fac(800_000))
                rtp.verify_episode_replay(ep, text_provider=provider)
                rec = tfda.evaluate_single_episode(ep, trap_info)
                spot = summary["policies"][pid]["spot_episodes"][f"{tier}_800000"]
                assert rec["score"] == pytest.approx(spot["score"], abs=1e-5)
                assert rec["accused"] == spot["accused"]
                assert rec["correct"] is spot["correct"]
                assert rec["decoy_false_accuse"] is spot["decoy_false_accuse"]
                assert rec["trap_false_accuse"] is spot["trap_false_accuse"]
                assert rec["trace_hex"] == spot["trace_hex"]

    assert (time.perf_counter() - t0) < 10.0
    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - fn_solver
    ) == set()
