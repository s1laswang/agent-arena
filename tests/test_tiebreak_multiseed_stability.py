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
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_PRELOADED_HEAVY = {m for m in ("torch", "transformers") if m in sys.modules}
_PRELOADED_SOLVER = {
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
}

from canary.env import Env
from canary.eval import run_episode
from canary.text.template import TemplateProvider
import scripts.tiebreak_multiseed_stability_audit as msa

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_multiseed_stability_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "multiseed_stability" / "multiseed_stability_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_multiseed_stability.md"
SELF_PATH = Path(__file__).resolve()


@pytest.fixture(scope="module")
def loaded_factories() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
    return msa._load_policy_factories(REPO_ROOT)


def test_source_hygiene_and_strict_ast_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_pkgs = {"torch", "transformers", "subprocess"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = msa.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    assert root_mod not in forbidden_pkgs
                    assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_mod = node.module.split(".")[0]
                assert root_mod not in forbidden_pkgs
                assert not node.module.startswith(("canary.solver", "canary.world"))
                if node.module == "canary":
                    imported = {a.name for a in node.names}
                    assert "solver" not in imported
                    assert "world" not in imported

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - _PRELOADED_HEAVY) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - _PRELOADED_SOLVER
    ) == set()

    import scripts.verify_tiebreak_submission as gate

    monkeypatch.chdir(REPO_ROOT)
    mod_errs, _ = gate._audit_policy_module_ast(
        "scripts/tiebreak_multiseed_stability_audit.py",
        SCRIPT_PATH,
    )
    assert mod_errs == []


def test_committed_summary_and_markdown_fast_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert SUMMARY_PATH.stat().st_size < 75 * 1024
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()
    assert msa.MAX_CHECK_SECONDS == 15.0

    t0 = time.perf_counter()
    rc = msa.main(["--check"])
    dt = time.perf_counter() - t0
    assert rc == 0
    assert dt < 10.0
    out_human = capsys.readouterr().out
    assert "OK: verified" in out_human
    assert "20/20 positive CIs" in out_human

    rc_json = msa.main(["--check", "--json"])
    assert rc_json == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    ver_art = msa.verify_artifacts(root=REPO_ROOT)
    assert ver_art["passed"] is True
    assert ver_art["errors"] == []

    raw_json = SUMMARY_PATH.read_text(encoding="utf-8")
    md_text = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii()
    assert md_text.isascii()

    summary = json.loads(raw_json)
    assert md_text == msa.render_markdown_report(summary)
    assert msa._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d+\b", raw_json):
        assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["num_world_secrets"] == 5
    assert summary["episodes_per_secret"] == 90
    assert summary["episodes_per_policy"] == 450
    assert summary["seed_isolation"]["judge_episodes_touched"] == 0
    assert summary["seed_isolation"]["dev_episodes_touched"] == 0
    assert summary["seed_isolation"]["train_episodes_in_heldout_eval"] == 0

    totals = summary["totals"]
    assert totals["policies_audited"] == 4
    assert totals["world_secrets_audited"] == 5
    assert totals["total_secret_cells"] == 20
    assert totals["positive_secret_cells_vs_abstain"] == 20
    assert totals["positive_secret_cells_vs_untrained"] == 20
    assert totals["primary_trained_episodes"] == 1800
    assert totals["fresh_env_replays_verified"] == 1800
    assert totals["all_policies_excess_tau_below_003"] is True
    assert totals["max_policy_excess_inter_secret_tau"] < 0.03

    vc = summary["verda_grpo_contrast"]
    assert vc["verda_8k_runs_count"] == 4
    assert vc["verda_8k_runs_above_zero"] == 0
    assert vc["verda_8k_inter_run_score_sd"] > 0.40
    assert vc["min_verda_to_compact_sd_ratio"] > 10.0

    for pid in msa.POLICY_ORDER:
        pb = summary["policies"][pid]
        assert pb["total_episodes"] == 450
        assert pb["is_open_weight_llm"] is False
        st = pb["stability_summary"]
        assert st["positive_paired_ci95_vs_abstain_secrets"] == 5
        assert st["positive_paired_ci95_vs_untrained_secrets"] == 5
        assert st["min_paired_ci95_low_vs_abstain"] > 0.0
        assert st["min_luck_ev_ci95_low_vs_abstain"] > 0.0
        assert st["min_paired_ci95_low_vs_untrained"] > 0.0
        assert st["min_luck_ev_ci95_low_vs_untrained"] > 0.0
        assert st["excess_inter_secret_tau"] < 0.03


def test_shallow_ci_git_free_root_and_tamper_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/multiseed_stability/multiseed_stability_summary.json",
        "docs/reports/tiebreak_multiseed_stability.md",
        "results/tiebreak/experiment_ledger.json",
        "results/tiebreak/verda_multiseed/multiseed_summary.json",
        "scripts/tiebreak_multiseed_stability_audit.py",
    ):
        dst = work_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (work_root / ".git").exists()

    monkeypatch.setenv("PATH", "")
    assert msa.main(["--check", "--repo-root", str(work_root)]) == 0
    _ = capsys.readouterr()
    assert msa.main(["--check", "--root", str(work_root)]) == 0
    _ = capsys.readouterr()

    (work_root / ".git").mkdir()
    (work_root / ".git" / "shallow").write_text("c3ff6c08\n", encoding="utf-8")
    (work_root / ".git" / "HEAD").write_text("c3ff6c08\n", encoding="utf-8")
    assert msa.main(["--check", "--repo-root", str(work_root)]) == 0
    _ = capsys.readouterr()

    forbidden_sib = work_root / "results" / "tiebreak" / "multiseed_stability" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert msa.main(["--check", "--repo-root", str(work_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = work_root / "docs" / "reports" / "tiebreak_multiseed_stability.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md.replace("20/20", "19/20", 1), encoding="utf-8")
    assert msa.main(["--check", "--repo-root", str(work_root)]) == 1
    assert "out of sync" in capsys.readouterr().err

    md_copy.write_text(orig_md + "\nForbidden " + chr(0x2014) + " dash\n", encoding="utf-8")
    assert msa.main(["--check", "--repo-root", str(work_root)]) == 1
    assert "non-ASCII" in capsys.readouterr().err or "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = work_root / "results" / "tiebreak" / "multiseed_stability" / "multiseed_stability_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["rogue_judge_int"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert msa.main(["--check", "--repo-root", str(work_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_live_multi_secret_posterior_luck_ev_spotcheck(
    loaded_factories: tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any],
) -> None:
    import scripts.run_tiebreak_policy as rtp

    trained_facs, _, _, eb_opt = loaded_factories
    provider = TemplateProvider()
    spot_cases = (
        (msa.WORLD_SECRET_SPECS[0][1], "compact_linear_dagger", "easy", 800_000, True),
        (msa.WORLD_SECRET_SPECS[0][1], "tiny_mlp", "medium", 800_001, False),
        (msa.WORLD_SECRET_SPECS[0][1], "scaling_logistic", "hard", 800_002, False),
        (msa.WORLD_SECRET_SPECS[0][1], "empirical_bayes", "easy", 800_003, False),
        (msa.WORLD_SECRET_SPECS[1][1], "compact_linear_dagger", "easy", 800_000, False),
    )

    tags_seen: set[str] = set()
    secret_ep_digests: list[str] = []
    for sec_str, pid, tier, seed, do_replay in spot_cases:
        tags_seen.add(msa.compute_secret_tag(sec_str))
        with msa._scoped_world_secret(sec_str):
            env = Env(tier, seed, text_provider=provider)
            spec = env.tools_spec()
            instr = env.instruction()
            ep = run_episode(env, trained_facs[pid](seed))
            if do_replay:
                rtp.verify_episode_replay(ep, text_provider=provider)
            if pid == "compact_linear_dagger" and tier == "easy" and seed == 800_000:
                secret_ep_digests.append(msa._canonical_ep_sha(ep))
            ev, p_post, v_est = msa.compute_public_luck_adjusted_ev(ep, spec, instr, eb_opt)
            if ep.accused is None:
                assert ev == 0.0
                assert p_post is None
                assert v_est is None
            else:
                assert p_post is not None and 0.0 <= p_post <= 1.0
                assert v_est is not None and 0.0 <= v_est <= 1.0
                expected_ev = p_post * v_est - (1.0 - p_post) * 1.0
                assert abs(ev - expected_ev) < 1e-12
                assert -1.0 <= ev <= 1.0

    assert len(tags_seen) == 2
    assert len(secret_ep_digests) == 2 and secret_ep_digests[0] != secret_ep_digests[1]
    assert ({m for m in ("torch", "transformers") if m in sys.modules} - _PRELOADED_HEAVY) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - _PRELOADED_SOLVER
    ) == set()
