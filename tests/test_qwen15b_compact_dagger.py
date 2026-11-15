from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import shutil
import sys
import time
import tokenize

import pytest

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

from canary.env import Env
from canary.rules import HELDOUT_SEEDS, TRAIN_SEEDS
import scripts.verify_tiebreak_submission as gate
from train.eval_compact_hf import verify_episode_file
import train.qwen15b_compact_dagger as mod

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "train" / "qwen15b_compact_dagger.py"
SELF_PATH = Path(__file__).resolve()
ARTIFACT_DIR = REPO_ROOT / "results" / "tiebreak" / "qwen15b_compact_dagger"


def _build_scoped_ast_root(dst: Path) -> Path:
    stubs = {
        "train/compact_render.py": "CompactStubPolicy",
        "train/empirical_bayes_policy.py": "EmpiricalBayesStubPolicy",
        "scripts/tiebreak_scaling_calibration.py": "ScalingStubPolicy",
    }
    for rel_mod, cls_name in stubs.items():
        p = dst / rel_mod
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"class {cls_name}:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ready = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n",
            encoding="utf-8",
        )
    hf_stub = dst / "train" / "eval_compact_hf.py"
    hf_stub.parent.mkdir(parents=True, exist_ok=True)
    hf_stub.write_text("def run_compact_eval():\n    return {}\n", encoding="utf-8")

    mod_dst = dst / "train" / "qwen15b_compact_dagger.py"
    mod_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MODULE_PATH, mod_dst)
    return dst


def test_source_hygiene_and_ast_inference_isolation(tmp_path: Path) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    banned_top_imports = {"torch", "transformers", "peft"}

    for path in (MODULE_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    assert alias.name.split(".")[0] not in banned_top_imports
            elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                assert stmt.module.split(".")[0] not in banned_top_imports

    assert _IMPORT_DELTA_HEAVY == frozenset()
    scoped_root = _build_scoped_ast_root(tmp_path / "ast_scope")
    res = gate.check_ast_inference_isolation(root=scoped_root, strict=True)
    assert res.passed is True, res.errors
    assert "train/qwen15b_compact_dagger.py:QwenCompactPolicy" in res.metrics["policy_classes_checked"]
    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()


def test_qwen_compact_policy_and_teacher_seed_guards() -> None:
    replies = iter([
        '<tool_call>\n{"name": "list_employees", "arguments": {}}\n</tool_call>',
        "malformed output without json",
    ])
    env = Env(tier="easy", seed=105_000)
    pol = mod.QwenCompactPolicy(name="unit_compact", kv_reuse=False, generator=lambda _turn: next(replies))
    pol.reset(env.tools_spec(), env.instruction())

    t1, a1 = pol.act(env.history)
    assert (t1, a1) == ("list_employees", {})
    assert pol.invalid == 0
    env.call(t1, a1)

    t2, a2 = pol.act(env.history)
    assert (t2, a2) == ("status", {})
    assert pol.invalid == 1

    ct_tool, ct_args = mod.query_calibrated_teacher(env.instruction(), env.history, d_cut=None, max_calls=50)
    assert isinstance(ct_tool, str) and isinstance(ct_args, dict)

    for bad_seed in (0, 800_000, 900_000):
        with pytest.raises(ValueError, match="non-train seed"):
            mod._rollout_teacher_job(("easy", bad_seed, None, 20, 2))

    censored = mod._rollout_teacher_job(("easy", 105_000, 1, 45, 2))
    assert censored is not None
    assert censored["censored"] is True
    assert censored["end_reason"] == "horizon"
    assert censored["score"] == 0.0
    assert censored["correct"] is False
    assert len(censored["turns"]) >= 2


def test_tiny_end_to_end_pipeline_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    work_dir = tmp_path / "work"
    out_dir = tmp_path / "out"
    t0 = time.perf_counter()
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "torch", None)
        mp.setitem(sys.modules, "transformers", None)
        summary = mod.main([
            "--tiny",
            "--work-dir",
            str(work_dir),
            "--out-dir",
            str(out_dir),
        ])
    elapsed = time.perf_counter() - t0
    assert elapsed < 15.0
    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()

    summary_path = out_dir / "summary.json"
    table_path = out_dir / "table.md"
    assert summary_path.is_file()
    assert table_path.is_file()
    assert summary_path.stat().st_size <= 120 * 1024

    assert summary["run_id"] == "qwen15b-compact-dagger-v14"
    assert summary["n"] == 3
    assert summary["tiers"] == ["easy", "medium", "hard"]
    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["before"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["after"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    t_start, t_stop = summary["train_seeds"]["start"], summary["train_seeds"]["stop"]
    assert all(s in TRAIN_SEEDS for s in range(t_start, t_stop))
    e_start, e_stop = summary["eval_seeds"]["start"], summary["eval_seeds"]["stop"]
    assert all(s in HELDOUT_SEEDS for s in range(e_start, e_stop))

    for fname in ("before_episodes.jsonl", "after_episodes.jsonl"):
        ver = verify_episode_file(work_dir / fname, world_secret="canary-tiebreak-heldout-v14-eval-01")
        assert ver["replay_ok"] is True
        assert ver["excluded_count"] == 0

    table_errs: list[str] = []
    checked = gate._audit_generic_summary_table(table_path, summary_path, table_errs)
    assert not table_errs
    assert checked == 4


def test_committed_artifact_if_present() -> None:
    summary_path = ARTIFACT_DIR / "summary.json"
    table_path = ARTIFACT_DIR / "table.md"
    if not summary_path.is_file():
        return

    assert table_path.is_file()
    assert summary_path.stat().st_size <= 120 * 1024
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    md_txt = table_path.read_text(encoding="utf-8")
    assert em_dash not in md_txt
    assert en_dash not in md_txt

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["run_id"] == "qwen15b-compact-dagger-v14"
    assert data["n"] == 90
    assert data["tiers"] == ["easy", "medium", "hard"]
    assert data["replay_verified"] is True
    assert data["invalid_episodes"] == 0
    assert data["before"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert data["after"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert len(data["paired"]["deltas"]) == 90

    errs: list[str] = []
    checked = gate._audit_generic_summary_table(table_path, summary_path, errs)
    assert not errs
    assert checked == 4
