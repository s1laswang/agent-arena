from __future__ import annotations

import ast
import io
import json
import sys
import tokenize
from pathlib import Path

import pytest

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

from canary.env import Env
from train.export_calibrated_sft import (
    assert_train_seed,
    export,
    export_dpo_pairs,
    is_calibrated_record,
    main,
    run_annotated_rollout,
    run_censored_abstention_rollout,
    split_seeds,
    validate_train_seeds,
)
from train.render import KICKOFF, tool_content

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = REPO_ROOT / "train" / "export_calibrated_sft.py"
SELF_PATH = Path(__file__).resolve()


@pytest.fixture(scope="module")
def annotated_rollouts() -> dict[tuple[str, int], dict]:
    return {
        ("easy", 100_000): run_annotated_rollout("easy", 100_000),
        ("medium", 100_001): run_annotated_rollout("medium", 100_001),
    }


@pytest.fixture(scope="module")
def censored_rollouts() -> dict[tuple[str, int], dict]:
    return {
        ("easy", 100_000): run_censored_abstention_rollout("easy", 100_000),
        ("medium", 100_000): run_censored_abstention_rollout("medium", 100_000),
    }


def test_source_and_ast_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for path in (EXPORT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"comment tokens found in {path}"
        assert hash_char not in src, f"hash character found in {path}"
        assert em_dash not in src, f"em dash found in {path}"
        assert en_dash not in src, f"en dash found in {path}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in ("torch", "transformers")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in ("torch", "transformers")
    assert _IMPORT_DELTA_HEAVY == frozenset()


def test_seed_guards_strict() -> None:
    for valid_seed in (100_000, 150_000, 189_999, 190_000, 199_999):
        assert assert_train_seed(valid_seed) == valid_seed
    assert validate_train_seeds([100_000, 189_999, 190_000, 199_999]) == [
        100_000,
        189_999,
        190_000,
        199_999,
    ]

    for train_seed in (100_000, 189_999):
        assert assert_train_seed(train_seed, split="train") == train_seed
    for bad_train in (190_000, 199_999):
        with pytest.raises(ValueError):
            assert_train_seed(bad_train, split="train")
        with pytest.raises(ValueError):
            validate_train_seeds([100_000, bad_train], split="train")

    for val_seed in (190_000, 199_999):
        assert assert_train_seed(val_seed, split="val") == val_seed
    for bad_val in (100_000, 189_999):
        with pytest.raises(ValueError):
            assert_train_seed(bad_val, split="val")
        with pytest.raises(ValueError):
            validate_train_seeds([190_000, bad_val], split="val")

    forbidden_seeds = [
        -1,
        0,
        29,
        9_999,
        10_000,
        42_000,
        69_999,
        70_000,
        99_999,
        200_000,
        500_000,
        799_999,
        800_000,
        800_199,
        900_000,
        900_039,
    ]
    for bad_seed in forbidden_seeds:
        with pytest.raises(ValueError):
            assert_train_seed(bad_seed)
        with pytest.raises(ValueError):
            validate_train_seeds([100_000, bad_seed])

    with pytest.raises(ValueError):
        assert_train_seed(True)
    with pytest.raises(ValueError):
        assert_train_seed(100_000, split="heldout")

    tr = split_seeds("train", 5, offset=0)
    va = split_seeds("val", 5, offset=0)
    assert tr == [100_000, 100_001, 100_002, 100_003, 100_004]
    assert va == [190_000, 190_001, 190_002, 190_003, 190_004]
    assert not (set(tr) & set(va))
    with pytest.raises(ValueError):
        split_seeds("val", 10_001, offset=0)


def test_annotated_rollouts_and_calibration(annotated_rollouts: dict[tuple[str, int], dict]) -> None:
    required_keys = {
        "t",
        "day",
        "tool",
        "args",
        "top_emp",
        "top_p",
        "runner_up_emp",
        "runner_up_p",
        "entropy",
        "known_v",
        "breakeven_p",
        "ev_accuse",
    }
    for (tier, seed), rec in annotated_rollouts.items():
        assert rec["tier"] == tier
        assert rec["seed"] == seed
        assert rec["augmented_abstention"] is False
        steps = rec["step_posteriors"]
        assert isinstance(steps, list) and len(steps) > 0
        assert len(rec["messages"]) == 2 + 2 * len(steps)
        for idx, st in enumerate(steps):
            assert required_keys.issubset(st.keys())
            assert st["t"] == idx
            assert 0.0 <= st["top_p"] <= 1.0 + 1e-7
            assert 0.0 < st["breakeven_p"] <= 1.0
            assert st["runner_up_p"] <= st["top_p"] + 1e-7
        assert rec["final_top_p"] == steps[-1]["top_p"]
        assert rec["final_breakeven_p"] == steps[-1]["breakeven_p"]
        assert is_calibrated_record(rec) is True

    assert is_calibrated_record(
        {"end_reason": "accused", "correct": False, "score": -1.0, "final_top_p": 0.9, "final_breakeven_p": 0.6}
    ) is False
    assert is_calibrated_record(
        {"end_reason": "accused", "correct": True, "score": 0.5, "final_top_p": 0.4, "final_breakeven_p": 0.6}
    ) is False
    assert is_calibrated_record(
        {"end_reason": "horizon", "correct": False, "score": 0.0, "final_top_p": 0.7, "final_breakeven_p": 0.6}
    ) is False
    assert is_calibrated_record(
        {"end_reason": "tool_cap", "correct": False, "score": 0.0, "final_top_p": 0.2, "final_breakeven_p": 0.6}
    ) is False


def test_censored_abstention_rollouts_and_env_replay(censored_rollouts: dict[tuple[str, int], dict]) -> None:
    for (tier, seed), rec in censored_rollouts.items():
        assert rec["tier"] == tier
        assert rec["seed"] == seed
        assert rec["augmented_abstention"] is True
        assert rec["end_reason"] == "horizon"
        assert rec["score"] == 0.0
        assert rec["correct"] is False
        assert rec["final_top_p"] < rec["final_breakeven_p"]
        assert is_calibrated_record(rec) is True

        msgs = rec["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[1] == {"role": "user", "content": KICKOFF}
        assert len(msgs) == 2 + 2 * len(rec["step_posteriors"])

        env = Env(tier=tier, seed=seed)
        body = msgs[2:]
        assert len(body) % 2 == 0
        for i in range(0, len(body), 2):
            a_msg = body[i]
            t_msg = body[i + 1]
            assert a_msg["role"] == "assistant"
            assert t_msg["role"] == "tool"
            fc = a_msg["tool_calls"][0]["function"]
            tool_name = fc["name"]
            tool_args = dict(fc["arguments"])
            assert tool_name != "accuse"
            env.call(tool_name, tool_args)
            assert t_msg["content"] == tool_content(env.history[-1].result)

        assert env.done is True
        replayed = env.result("replay")
        assert replayed.score == 0.0
        assert replayed.end_reason == "horizon"
        assert replayed.correct is False
        assert replayed.final_day == rec["final_day"] == rec["n_days"]


def test_export_dpo_and_end_to_end_export(
    tmp_path: Path,
    annotated_rollouts: dict[tuple[str, int], dict],
    censored_rollouts: dict[tuple[str, int], dict],
    capsys: pytest.CaptureFixture[str],
) -> None:
    acc_pairs = export_dpo_pairs(annotated_rollouts[("easy", 100_000)])
    abs_pairs = export_dpo_pairs(censored_rollouts[("medium", 100_000)])
    assert len(acc_pairs) > 0
    assert len(abs_pairs) > 0
    for p in acc_pairs + abs_pairs:
        assert p["seed"] == 100_000
        assert p["margin_ev"] > 0.0
        assert p["chosen"] != p["rejected"]
        assert p["messages"][0]["role"] == "system"
        assert p["messages"][1] == {"role": "user", "content": KICKOFF}
        assert p["chosen"]["role"] == "assistant"
        assert p["rejected"]["role"] == "assistant"

    bad_rec = dict(annotated_rollouts[("easy", 100_000)], seed=800_000)
    with pytest.raises(ValueError):
        export_dpo_pairs(bad_rec)

    out_dir = tmp_path / "train_out"
    manifest = export(
        split="train",
        tiers=["easy"],
        n=2,
        out=str(out_dir),
        augment_abstentions=1,
        dpo=True,
        workers=1,
    )
    manifest_path = out_dir / "train-calibrated-manifest.json"
    sft_path = out_dir / "sft-train-easy.jsonl"
    dpo_path = out_dir / "dpo-train-easy.jsonl"
    assert manifest_path.exists()
    assert sft_path.exists()
    assert dpo_path.exists()

    disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert disk_manifest == manifest
    assert manifest["split"] == "train"
    assert manifest["dpo_enabled"] is True
    assert manifest["augment_abstentions_per_tier"] == 1
    assert manifest["abstain_oversample"] == 2
    assert manifest["files"] == ["sft-train-easy.jsonl", "dpo-train-easy.jsonl"]

    sft_rows = [json.loads(line) for line in sft_path.read_text(encoding="utf-8").splitlines()]
    dpo_rows = [json.loads(line) for line in dpo_path.read_text(encoding="utf-8").splitlines()]
    assert len(sft_rows) == manifest["sft_records_written"] >= 2
    assert len(dpo_rows) == manifest["dpo_pairs"] > 0

    aug_replicas = [r["oversample_replica"] for r in sft_rows if r["augmented_abstention"]]
    assert sorted(aug_replicas) == [0, 1]
    for r in sft_rows:
        assert 100_000 <= r["seed"] < 190_000
        assert is_calibrated_record(r) is True
        roles = [m["role"] for m in r["messages"][2:]]
        assert roles == ["assistant", "tool"] * (len(roles) // 2)

    for p in dpo_rows:
        assert 100_000 <= p["seed"] < 190_000
        assert p["margin_ev"] > 0.0
        assert p["chosen"] != p["rejected"]

    val_dir = tmp_path / "val_out"
    cli_manifest = main(
        ["--split", "val", "--tier", "easy", "--n", "1", "--out", str(val_dir), "--workers", "1"]
    )
    printed = json.loads(capsys.readouterr().out)
    assert printed == cli_manifest
    assert cli_manifest["split"] == "val"
    assert cli_manifest["abstain_oversample"] == 1
    assert (val_dir / "val-calibrated-manifest.json").exists()
