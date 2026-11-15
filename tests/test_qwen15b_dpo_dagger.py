from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.env import Env
import scripts.tiebreak_addendum_pack as addendum
import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.verify_tiebreak_submission as gate
from train.eval_compact_hf import DEFAULT_HELD_OUT_WORLD_SECRET, compute_world_secret_tag
import train.qwen15b_dpo_dagger as dpo_mod

MODULE_PATH = REPO_ROOT / "train" / "qwen15b_dpo_dagger.py"
SELF_PATH = Path(__file__).resolve()
RESULT_DIR = REPO_ROOT / "results" / "tiebreak" / "qwen15b_dpo_dagger"


def test_source_hygiene_and_ast_inference_isolation() -> None:
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

    ast_res = gate.check_ast_inference_isolation(
        root=REPO_ROOT,
        extra_paths=[MODULE_PATH],
        strict=True,
    )
    assert ast_res.passed is True, ast_res.errors
    assert "train/qwen15b_dpo_dagger.py:QwenCompactDpoPolicy" in ast_res.metrics["policy_classes_checked"]
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_seed_plan_hygiene_and_rejections() -> None:
    plan = dpo_mod.validate_seed_plan(
        range(dpo_mod.SFT_SEED_START, dpo_mod.SFT_SEED_STOP),
        range(dpo_mod.DAGGER_R1_START, dpo_mod.DAGGER_R1_STOP),
        range(dpo_mod.DAGGER_R2_START, dpo_mod.DAGGER_R2_STOP),
        range(dpo_mod.EVAL_SEED_START, dpo_mod.EVAL_SEED_STOP),
    )
    assert len(plan["sft"]) == 240
    assert len(plan["r1"]) == 90
    assert len(plan["r2"]) == 90
    assert len(plan["eval"]) == 30
    assert len(plan["train_all"]) == 420
    assert min(plan["train_all"]) >= 100_000
    assert max(plan["train_all"]) < 200_000
    assert set(plan["train_all"]).isdisjoint(plan["eval"])

    with pytest.raises(ValueError, match="pairwise disjoint"):
        dpo_mod.validate_seed_plan([106_000], [106_000], [106_001], [800_000])

    with pytest.raises(ValueError, match="outside TRAIN_SEEDS"):
        dpo_mod.validate_seed_plan([0], [106_001], [106_002], [800_000])

    with pytest.raises(ValueError, match="outside TRAIN_SEEDS"):
        dpo_mod.validate_seed_plan([900_000], [106_001], [106_002], [800_000])

    with pytest.raises(ValueError, match="outside HELDOUT_SEEDS"):
        dpo_mod.validate_seed_plan([106_000], [106_001], [106_002], [0])


def test_calibrated_teacher_and_compact_policy_isolation() -> None:
    env = Env(tier="easy", seed=106_000)
    ins, ts = env.instruction(), env.tools_spec()
    step0 = dpo_mod.calibrated_teacher_step(ins, ts, env.history, stop_margin=0.06)
    assert step0["tool"] == "list_employees"
    assert abs(sum(step0["post"].values()) - 1.0) < 1e-6
    assert step0["threshold_p"] >= step0["breakeven_p"] + 0.06 - 1e-9

    env.call(step0["tool"], step0["args"])
    censored = dpo_mod.calibrated_teacher_step(
        ins, ts, env.history, stop_margin=0.06, censor_canary_after_day=0
    )
    assert censored["tool"] != "accuse"
    assert censored["tool"] != "plant_canary"

    eval_env = Env(tier="easy", seed=800_000)
    pol = dpo_mod.QwenCompactDpoPolicy(
        generator=lambda _turn: '<tool_call>\n{"name": "list_employees", "arguments": {}}\n</tool_call>'
    )
    pol.reset(eval_env.tools_spec(), eval_env.instruction())
    tool_name, tool_args = pol.act(eval_env.history)
    assert tool_name == "list_employees"
    assert tool_args == {}
    assert pol.invalid == 0


def test_tiny_cli_smoke_end_to_end(tmp_path: Path) -> None:
    scratch_dir = tmp_path / "scratch"
    out_summary = tmp_path / "summary.json"
    out_table = tmp_path / "table.md"

    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "train.qwen15b_dpo_dagger",
            "--tiny",
            "--tiers",
            "easy",
            "--scratch-dir",
            str(scratch_dir),
            "--out-summary",
            str(out_summary),
            "--out-table",
            str(out_table),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    elapsed = time.perf_counter() - t0
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert elapsed < 15.0

    assert out_summary.is_file()
    assert out_table.is_file()
    assert out_summary.stat().st_size <= 120 * 1024

    payload = json.loads(out_summary.read_text(encoding="utf-8"))
    expected_tag = compute_world_secret_tag(DEFAULT_HELD_OUT_WORLD_SECRET)
    assert payload["replay_verified"] is True
    assert payload["invalid_episodes"] == 0
    assert payload["world_secret_tag"] == expected_tag
    assert payload["before"]["world_secret_tag"] == expected_tag
    assert payload["sft_only"]["world_secret_tag"] == expected_tag
    assert payload["after"]["world_secret_tag"] == expected_tag
    assert payload["n"] == 1
    assert len(payload["paired"]["deltas"]) == 1

    errs: list[str] = []
    checked = gate._audit_generic_summary_table(out_table, out_summary, errs)
    assert errs == []
    assert checked >= 4

    led_res = ledger_mod.validate_experiment_summary(payload, str(out_summary))
    assert led_res["gates"]["gate1_seed_hygiene"] is True
    assert led_res["gates"]["gate2_paired_world_secret"] is True

    add_res = addendum.evaluate_run_summary(payload, str(out_summary), repo_root=REPO_ROOT)
    assert add_res["track"] == "track_1"
    assert add_res["is_open_weight_llm"] is True
    assert add_res["criteria"]["train_eval_disjoint"] is True
    assert add_res["criteria"]["autonomous_inference"] is True


def test_committed_v100_result_artifacts_if_present() -> None:
    summary_path = RESULT_DIR / "summary.json"
    table_path = RESULT_DIR / "table.md"
    if not summary_path.is_file() and not table_path.is_file():
        return

    assert summary_path.is_file()
    assert table_path.is_file()
    assert summary_path.stat().st_size <= 120 * 1024

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    expected_tag = compute_world_secret_tag(DEFAULT_HELD_OUT_WORLD_SECRET)
    assert data["tiers"] == ["easy", "medium", "hard"]
    assert data["n"] == 90
    assert data["eval_seeds"] == {"start": 800_000, "stop": 800_030}
    assert data["train_seeds"]["start"] >= 100_000
    assert data["train_seeds"]["stop"] <= 200_000
    assert data["replay_verified"] is True
    assert data["invalid_episodes"] == 0
    assert data["world_secret_tag"] == expected_tag
    assert data["before"]["world_secret_tag"] == expected_tag
    assert data["sft_only"]["world_secret_tag"] == expected_tag
    assert data["after"]["world_secret_tag"] == expected_tag
    assert len(data["paired"]["deltas"]) == 90

    md_txt = table_path.read_text(encoding="utf-8")
    assert chr(0x2014) not in md_txt
    assert chr(0x2013) not in md_txt
    errs: list[str] = []
    checked = gate._audit_generic_summary_table(table_path, summary_path, errs)
    assert errs == []
    assert checked >= 4
