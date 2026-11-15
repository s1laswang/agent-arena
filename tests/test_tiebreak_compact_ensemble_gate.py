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

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_IMPORT_SOLVER = frozenset(
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
)

import scripts.tiebreak_compact_ensemble_gate as tceg

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_compact_ensemble_gate.py"
SUMMARY_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "compact_ensemble" / "compact_ensemble_summary.json"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_compact_ensemble_gate.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_ast_policy_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers", "subprocess"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tceg.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

    self_src = SELF_PATH.read_text(encoding="utf-8")
    self_toks = list(tokenize.generate_tokens(io.StringIO(self_src).readline))
    assert not [t for t in self_toks if t.type == tokenize.COMMENT]
    self_tree = ast.parse(self_src, filename=str(SELF_PATH))
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

    ast_errs, ast_classes = vts._audit_policy_module_ast(
        "scripts/tiebreak_compact_ensemble_gate.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    assert "scripts/tiebreak_compact_ensemble_gate.py:EpistemicGatedEnsemblePolicy" in ast_classes


def test_check_cli_json_mode_and_heldout_ensemble_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tceg.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_human = tceg.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < tceg.MAX_CHECK_SECONDS
    assert "OK: verified compact ensemble gate" in out_human
    assert "1080/1080 replays" in out_human
    assert "6/6 positive CIs" in out_human

    rc_json = tceg.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tceg.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < tceg.MAX_CHECK_SECONDS

    raw_json = raw_bytes.decode("utf-8")
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii()
    assert md_txt.isascii()

    summary = json.loads(raw_json)
    assert md_txt == tceg.render_markdown_report(summary)
    assert tceg._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d{6,}\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < tceg.JUDGE_SEED_MIN

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["train_seed_range"] == "109800..109829"
    assert summary["constituent_param_count"] == 13171
    assert summary["episodes_per_policy"] == 90
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["compact_policies_are_open_weight_llm"] is False
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"

    pols = summary["policies"]
    for pid in tceg.CONSTITUENT_ORDER + tceg.ENSEMBLE_ORDER:
        pb = pols[pid]
        assert pb["is_open_weight_llm"] is False
        assert pb["context_tokens"] == 0
        assert pb["overall"]["replay_verified"] is True
        assert pb["paired_vs_do_nothing"]["ci95_low"] > 0.0

    eg = pols["epistemic_gated_ensemble"]
    h2h = summary["ensemble_head_to_head"]
    assert eg["overall"]["mean_score"] == pytest.approx(0.6564, abs=5e-4)
    assert eg["overall"]["wrong_accuse_rate"] == 0.0
    assert eg["overall"]["sub_breakeven_accuse_count"] == 0
    assert eg["overall"]["calibration"]["multiclass_brier"] < min(
        pols[c]["overall"]["calibration"]["multiclass_brier"] for c in tceg.CONSTITUENT_ORDER
    )
    vs_unan = h2h["paired_epistemic_gated_vs_peers"]["unanimous_consensus_ensemble"]
    assert vs_unan["ci95_low"] > 0.0
    assert vs_unan["losses"] == 0


def test_gitless_shallow_repo_root_empty_path_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        tceg.DEFAULT_OUT_JSON,
        tceg.DEFAULT_OUT_MD,
        tceg.LEDGER_REL,
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    t0 = time.perf_counter()
    assert tceg.main(["--check", "--repo-root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t0) < tceg.MAX_CHECK_SECONDS
    _ = capsys.readouterr()

    (no_git_root / ".git").mkdir()
    (no_git_root / ".git" / "shallow").write_text("560ddde3\n", encoding="utf-8")
    (no_git_root / ".git" / "HEAD").write_text("560ddde3\n", encoding="utf-8")
    t1 = time.perf_counter()
    assert tceg.main(["--check", "--root", str(no_git_root), "--json"]) == 0
    assert (time.perf_counter() - t1) < tceg.MAX_CHECK_SECONDS
    assert json.loads(capsys.readouterr().out)["passed"] is True

    sib_dir = (no_git_root / tceg.DEFAULT_OUT_JSON).parent
    for bad_name in ("summary.json", "table.md"):
        (sib_dir / bad_name).write_text("{}\n", encoding="utf-8")
    assert tceg.main(["--check", "--repo-root", str(no_git_root)]) == 1
    sib_err = capsys.readouterr().err
    assert "summary.json" in sib_err and "table.md" in sib_err
    for bad_name in ("summary.json", "table.md"):
        (sib_dir / bad_name).unlink()

    md_copy = no_git_root / tceg.DEFAULT_OUT_MD
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(
        orig_md + "\nPre-registered seeds 0..29 claim.\nBad " + chr(0x2014) + " dash.\n",
        encoding="utf-8",
    )
    assert tceg.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_md = capsys.readouterr().err
    assert "Panel Fix A" in err_md
    assert "em dash" in err_md
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = no_git_root / tceg.DEFAULT_OUT_JSON
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    bad_summary["policies"]["epistemic_gated_ensemble"]["overall"]["mean_score"] = 0.9999
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tceg.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_json = capsys.readouterr().err
    assert "900000" in err_json
    assert "recomputed mean/CI disagrees" in err_json


def test_epistemic_disagreement_math_and_spot_episode_replay() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    w_unif = np.full(4, 0.25, dtype=np.float64)
    agree_mat = np.tile(np.array([0.85, 0.05, 0.05, 0.05], dtype=np.float64), (4, 1))
    d_agree = tceg.compute_epistemic_disagreement(agree_mat, w_unif)
    assert d_agree["jsd_norm"] == pytest.approx(0.0, abs=1e-9)
    assert d_agree["consensus_count"] == 4
    assert d_agree["pairwise_agreement"] == pytest.approx(1.0, abs=1e-9)

    split_mat = np.eye(4, dtype=np.float64) * 0.88 + 0.03
    d_split = tceg.compute_epistemic_disagreement(split_mat, w_unif)
    assert d_split["jsd_norm"] > 0.45
    assert d_split["consensus_count"] == 1
    assert d_split["pairwise_agreement"] == pytest.approx(0.0, abs=1e-9)

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    sel_cfg = summary["policies"]["epistemic_gated_ensemble"]["gate_config"]
    constituents = tceg._load_constituent_factories(REPO_ROOT)
    ens_fac = tceg._make_ensemble_factory(constituents, sel_cfg, unanimous=False)
    tp = TemplateProvider()

    with tceg._scoped_secret(tceg.HELDOUT_WORLD_SECRET):
        ep = run_episode(Env("easy", 800_000, text_provider=tp), ens_fac(800_000))
        assert rtp.verify_episode_replay(ep, text_provider=tp) is True
        assert round(float(ep.score), 4) == pytest.approx(
            summary["policies"]["epistemic_gated_ensemble"]["scores"][0], abs=1e-4
        )

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - fn_solver
    ) == set()
