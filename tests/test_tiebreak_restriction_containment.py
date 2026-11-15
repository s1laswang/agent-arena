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

_BEFORE_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_SOLVER = frozenset(
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
)

import scripts.tiebreak_restriction_containment_audit as trca

_DELTA_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_HEAVY
_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_restriction_containment_audit.py"
SUMMARY_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "restriction_containment" / "restriction_containment_summary.json"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_restriction_containment.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_ast_policy_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = trca.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

        tree = ast.parse(src, filename=str(py_path))
        bad_roots = {"torch", "transformers", "subprocess"} if py_path == SCRIPT_PATH else {"torch", "transformers"}
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

    toks = list(tokenize.generate_tokens(io.StringIO(SELF_PATH.read_text(encoding="utf-8")).readline))
    assert not [t for t in toks if t.type == tokenize.COMMENT]
    assert _DELTA_HEAVY == frozenset()
    assert _DELTA_SOLVER == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, checked_list = vts._audit_policy_module_ast(
        "scripts/tiebreak_restriction_containment_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    checked = set(checked_list)
    assert "scripts/tiebreak_restriction_containment_audit.py:ContainmentBasePolicy" in checked
    assert "scripts/tiebreak_restriction_containment_audit.py:NoRestrictPolicyWrapper" in checked
    assert "scripts/tiebreak_restriction_containment_audit.py:DefaultPolicy" in checked
    assert "scripts/tiebreak_restriction_containment_audit.py:TrainTunedContainmentWrapper" in checked
    assert "scripts/tiebreak_restriction_containment_audit.py:AggressiveOverRestrictWrapper" in checked


def test_check_cli_json_mode_and_heldout_decomposition_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < trca.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_human = trca.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < 10.0
    assert "OK: verified" in out_human
    assert "720 held-out episodes" in out_human

    rc_json = trca.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == trca.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    raw_json = raw_bytes.decode("utf-8")
    summary = json.loads(raw_json)
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert md_txt == trca.render_markdown_report(summary)
    assert trca._scan_json_for_judge_numbers(summary, raw_json) == []
    for dig_match in re.finditer(r"\d+", raw_json):
        assert int(dig_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["train_seed_range"] == "109700..109729"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["episodes_per_condition"] == 90
    assert summary["totals"]["heldout_episodes"] == 720
    assert summary["totals"]["heldout_replays_verified"] == 720
    assert summary["totals"]["train_tuning_episodes"] == 1080

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_rolled_out"] == 0
    assert iso["train_heldout_overlap_count"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
    assert pe["audited_policies_are_open_weight_llm"] is False

    eb = summary["policies"]["empirical_bayes"]
    cd = summary["policies"]["compact_linear_dagger"]
    assert eb["param_count"] == 11
    assert cd["param_count"] == 785
    assert eb["conditions"]["default_unmodified"]["overall"]["mean_score"] == pytest.approx(0.62233, abs=2e-4)
    assert eb["conditions"]["no_restrict"]["overall"]["mean_score"] == pytest.approx(0.62233, abs=2e-4)
    assert eb["conditions"]["no_restrict"]["overall"]["mean_restrict_calls"] == 0.0
    assert cd["conditions"]["default_unmodified"]["overall"]["mean_score"] == pytest.approx(0.66322, abs=2e-4)
    assert cd["conditions"]["no_restrict"]["overall"]["mean_score"] == pytest.approx(0.66322, abs=2e-4)
    assert cd["conditions"]["no_restrict"]["overall"]["mean_restrict_calls"] == 0.0

    for pblock in (eb, cd):
        tuned = pblock["conditions"]["train_tuned_containment"]
        over = pblock["conditions"]["aggressive_over_restrict"]
        assert tuned["overall"]["mean_restrict_calls"] > 0.5
        assert tuned["overall"]["wrong_accuse_rate"] == 0.0
        assert over["overall"]["mean_restrict_calls"] > 4.0
        assert over["paired_vs_unmodified"]["mean_delta"] < -0.15
        assert over["paired_vs_unmodified"]["ci95_high"] < -0.10
        assert over["overall"]["abstain_rate"] > 0.25


def test_gitless_shallow_repo_root_and_empty_path_safety(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "results" / "tiebreak" / "restriction_containment").mkdir(parents=True)
    (tmp_path / "docs" / "reports").mkdir(parents=True)
    shutil.copy2(SCRIPT_PATH, tmp_path / "scripts" / SCRIPT_PATH.name)
    shutil.copy2(SUMMARY_PATH, tmp_path / trca.DEFAULT_OUT_JSON)
    shutil.copy2(REPORT_PATH, tmp_path / trca.DEFAULT_OUT_MD)

    monkeypatch.setenv("PATH", "")
    rc_ok = trca.main(["--check", "--repo-root", str(tmp_path)])
    capsys.readouterr()
    assert rc_ok == 0

    rc_root = trca.main(["--check", "--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_root == 0
    assert payload["passed"] is True

    bad_sibling = (tmp_path / trca.DEFAULT_OUT_JSON).parent / "summary.json"
    bad_sibling.write_text("{}", encoding="utf-8")
    rc_bad = trca.main(["--check", "--repo-root", str(tmp_path)])
    capsys.readouterr()
    assert rc_bad == 1


def test_live_wrapper_suppression_and_fresh_env_replay_spotcheck() -> None:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    t0 = time.perf_counter()
    provider = TemplateProvider()
    bundle = trca.load_base_policy_bundle(REPO_ROOT)
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

    eb_p = bundle["empirical_bayes"]["eb_params"]
    cd_w = bundle["compact_linear_dagger"]["linear_weights"]
    cd_tau = float(summary["policies"]["compact_linear_dagger"]["selected_tau_restrict"])

    no_rest_pol = trca.NoRestrictPolicyWrapper(
        policy="empirical_bayes",
        eb_params=eb_p,
        extra_pre_queue=[("restrict_access", {"employee": "e00"})],
        seed=800_000,
    )
    tuned_pol = trca.TrainTunedContainmentWrapper(
        policy="compact_linear_dagger",
        tau_restrict=cd_tau,
        linear_weights=cd_w,
        seed=800_000,
    )
    over_pol = trca.AggressiveOverRestrictWrapper(
        policy="empirical_bayes",
        eb_params=eb_p,
        seed=800_000,
    )

    with trca._scoped_world_secret(trca.HELDOUT_WORLD_SECRET):
        ep_no = run_episode(Env("easy", 800_000, text_provider=provider), no_rest_pol)
        rtp.verify_episode_replay(ep_no, text_provider=provider)
        ep_tuned = run_episode(Env("easy", 800_001, text_provider=provider), tuned_pol)
        rtp.verify_episode_replay(ep_tuned, text_provider=provider)
        ep_over = run_episode(Env("easy", 800_000, text_provider=provider), over_pol)
        rtp.verify_episode_replay(ep_over, text_provider=provider)

    assert sum(1 for st in ep_no.steps if st.tool == "restrict_access") == 0
    assert sum(1 for st in ep_over.steps if st.tool == "restrict_access" and st.result.get("ok")) >= 1
    assert time.perf_counter() - t0 < 10.0
