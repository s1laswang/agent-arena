from __future__ import annotations

import ast
import dataclasses
import io
import json
from pathlib import Path
import sys
import time
import tokenize
from typing import Any

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS
from canary.types import Step
import scripts.tiebreak_addendum_pack as addendum_mod
import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.verify_tiebreak_submission as gate
from train.compact_render import CompactHFPolicy
import train.compact_lora_sft as mod
from train.eval_compact_hf import verify_episode_file

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "train" / "compact_lora_sft.py"
COMMITTED_MANIFEST_PATH = REPO_ROOT / "results" / "tiebreak" / "qwen05b_compact_dagger" / "export_manifest.json"
SHARED_EXPORT_DIR = Path("/tmp/fleet-silas/shared/tiebreak-v100/qwen05b_compact_dagger")
SELF_PATH = Path(__file__).resolve()


class _DeterministicMockTokenizer:
    pad_token_id = 0
    eos_token_id = 2

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {"<pad>": 0, "<bos>": 1, "<eos>": 2}

    def _encode_text(self, text: str) -> list[int]:
        ids: list[int] = [1]
        for tok in text.split():
            if tok not in self._vocab:
                self._vocab[tok] = len(self._vocab) + 10
            ids.append(self._vocab[tok])
        return ids

    def apply_chat_template(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tokenize: bool = True,
        add_generation_prompt: bool = False,
    ) -> list[int] | str:
        txt = mod.load_compact_render().render_compact_prompt_text(
            {"messages": messages, "tools": tools or []},
            add_generation_prompt=add_generation_prompt,
        )
        if not tokenize:
            return txt
        ids = self._encode_text(txt)
        if not add_generation_prompt:
            ids.append(self.eos_token_id)
        return ids


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
                    assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                assert stmt.module.split(".")[0] not in banned_top_imports
                assert not stmt.module.startswith(("canary.solver", "canary.world"))

    mod_tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    for node in ast.walk(mod_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("canary.world")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("canary.world")

    res = gate.check_ast_inference_isolation(root=REPO_ROOT, extra_paths=[MODULE_PATH], strict=True)
    assert res.passed is True, res.errors
    assert "train/compact_lora_sft.py:CompactLoRAPolicy" in res.metrics["policy_classes_checked"]
    add_errs, add_classes = addendum_mod.audit_inference_module_ast("train/compact_lora_sft.py", MODULE_PATH)
    assert add_errs == []
    assert "train/compact_lora_sft.py:CompactLoRAPolicy" in add_classes
    assert issubclass(mod.CompactLoRAPolicy, CompactHFPolicy)
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    forbidden_weight_exts = {".safetensors", ".bin", ".pt", ".pth", ".ckpt", ".npz"}
    for scan_dir in (REPO_ROOT / "train", REPO_ROOT / "results" / "tiebreak"):
        for fpath in scan_dir.rglob("*"):
            if fpath.is_file() and "__pycache__" not in fpath.parts:
                assert fpath.suffix.lower() not in forbidden_weight_exts


def test_seed_hygiene_rejections() -> None:
    assert mod.assert_train_seed(100_000, split="train") == 100_000
    assert mod.assert_train_seed(189_999, split="train") == 189_999
    assert mod.assert_train_seed(190_000, split="val") == 190_000
    assert mod.assert_train_seed(199_999, split="val") == 199_999

    for dev_s in (0, 29, 9_999):
        assert dev_s in DEV_SEEDS
        with pytest.raises(ValueError, match="DEV_SEEDS"):
            mod.assert_train_seed(dev_s)
        with pytest.raises(ValueError, match="DEV_SEEDS"):
            mod.validate_train_seeds([100_000, dev_s])

    for held_s in (800_000, 800_029, 800_199):
        assert held_s in HELDOUT_SEEDS
        with pytest.raises(ValueError, match="HELDOUT_SEEDS"):
            mod.assert_train_seed(held_s)
        with pytest.raises(ValueError, match="HELDOUT_SEEDS"):
            mod.validate_train_seeds([100_001, held_s])

    for judge_s in (900_000, 900_039, 950_000):
        with pytest.raises(ValueError, match="JUDGE_SEEDS"):
            mod.assert_train_seed(judge_s)
        with pytest.raises(ValueError, match="JUDGE_SEEDS"):
            mod.validate_train_seeds([100_002, judge_s])

    for bad_other in (-5, True, 10_000, 99_999, 200_000):
        with pytest.raises(ValueError):
            mod.assert_train_seed(bad_other)

    with pytest.raises(ValueError, match="outside train split"):
        mod.assert_train_seed(190_000, split="train")
    with pytest.raises(ValueError, match="outside val split"):
        mod.assert_train_seed(100_000, split="val")

    assert mod.assert_eval_seed(800_000, "heldout") == 800_000
    assert mod.assert_eval_seed(800_199, "heldout") == 800_199
    assert mod.assert_eval_seed(0, "dev") == 0
    assert mod.assert_eval_seed(29, "dev") == 29

    for train_s in (100_000, 150_000, 199_999):
        assert train_s in TRAIN_SEEDS
        with pytest.raises(ValueError, match="TRAIN_SEEDS"):
            mod.assert_eval_seed(train_s, "heldout")
        with pytest.raises(ValueError, match="TRAIN_SEEDS"):
            mod.assert_eval_seed(train_s, "dev")

    for judge_s in (900_000, 900_015, 900_039):
        assert judge_s in JUDGE_SEEDS
        with pytest.raises(ValueError, match="JUDGE_SEEDS"):
            mod.assert_eval_seed(judge_s, "heldout")
        with pytest.raises(ValueError, match="JUDGE_SEEDS"):
            mod.assert_eval_seed(judge_s, "dev")

    for non_heldout in (-1, 0, 29, 799_999, 800_200):
        with pytest.raises(ValueError, match="HELDOUT_SEEDS"):
            mod.assert_eval_seed(non_heldout, "heldout")

    mod.assert_all_splits_disjoint([100_000, 100_001], [190_000], [800_000, 800_001], [0, 1])
    with pytest.raises(ValueError):
        mod.assert_all_splits_disjoint([100_000], [190_000], [100_000], [0])
    with pytest.raises(ValueError):
        mod.assert_all_splits_disjoint([100_000], [190_000], [900_000], [0])


def test_compact_sft_dpo_formatting_and_calibrated_abstention_filtering() -> None:
    assert mod.is_calibrated_compact_bundle({
        "end_reason": "accused",
        "correct": True,
        "score": 0.90,
        "final_top_p": 0.92,
        "final_breakeven_p": 0.53,
    }) is True
    assert mod.is_calibrated_compact_bundle({
        "end_reason": "accused",
        "correct": False,
        "score": -1.0,
        "final_top_p": 0.92,
        "final_breakeven_p": 0.53,
    }) is False
    assert mod.is_calibrated_compact_bundle({
        "end_reason": "accused",
        "correct": True,
        "score": 0.95,
        "final_top_p": 0.25,
        "final_breakeven_p": 0.53,
    }) is False
    assert mod.is_calibrated_compact_bundle({
        "end_reason": "horizon",
        "correct": False,
        "score": 0.0,
        "final_top_p": 0.30,
        "final_breakeven_p": 0.55,
    }) is True
    assert mod.is_calibrated_compact_bundle({
        "end_reason": "horizon",
        "correct": False,
        "score": 0.0,
        "final_top_p": 0.85,
        "final_breakeven_p": 0.55,
    }) is False

    nat_bundle = mod.run_natural_compact_rollout("easy", 100_000, split="train")
    assert mod.is_calibrated_compact_bundle(nat_bundle) is True
    sft_rows, dpo_pairs = mod.build_compact_episode_sft_and_dpo(nat_bundle, tail_turns=4, split="train")
    assert len(sft_rows) > len(nat_bundle["meta_rec"]["step_posteriors"])
    assert any(r["target_tool"] == "accuse" and r["oversample_total"] >= 6 for r in sft_rows)
    assert all("STATE:" in r["messages"][1]["content"] for r in sft_rows)
    assert len(dpo_pairs) >= 2
    pair_types = {p["pair_type"] for p in dpo_pairs}
    assert "wrong_target_accuse" in pair_types or "stall_when_ev_pos" in pair_types

    uncal_bundle = {
        "ep": nat_bundle["ep"],
        "instruction": nat_bundle["instruction"],
        "tools_spec": nat_bundle["tools_spec"],
        "meta_rec": {
            **nat_bundle["meta_rec"],
            "correct": False,
            "score": -1.0,
            "end_reason": "accused",
        },
    }
    rej_sft, rej_dpo = mod.build_compact_episode_sft_and_dpo(uncal_bundle, tail_turns=4, split="train")
    assert rej_sft == []
    assert rej_dpo == []

    assert mod.turn_oversample_count(
        turn_idx=5,
        n_turns=20,
        target_tool="advance_day",
        step_day=6,
        n_days=14,
        end_reason="horizon",
        augmented_abstention=True,
        censor_d_cut=2,
        split="train",
    ) == 0
    assert mod.turn_oversample_count(
        turn_idx=19,
        n_turns=20,
        target_tool="advance_day",
        step_day=14,
        n_days=14,
        end_reason="horizon",
        augmented_abstention=True,
        censor_d_cut=2,
        split="train",
    ) == 6

    tok = _DeterministicMockTokenizer()
    packed_turn = mod.pack_compact_turn_ids(sft_rows[0], tok, max_len=2048)
    assert packed_turn is not None
    full_ids, labels, prompt_len = packed_turn
    assert 0 < prompt_len < len(full_ids)
    assert labels[:prompt_len] == [-100] * prompt_len
    assert labels[prompt_len:] == full_ids[prompt_len:]

    packed_pair = mod.pack_compact_dpo_pair_ids(dpo_pairs[0], tok, max_len=2048)
    assert packed_pair is not None
    assert packed_pair["chosen_ids"] != packed_pair["rejected_ids"]
    dpo_m = mod.dpo_loss_from_logprobs_py([-0.4, -0.5], [-1.5, -1.3], [-1.0, -1.0], [-1.0, -1.0], beta=0.15)
    assert dpo_m["pref_acc"] == 1.0
    assert dpo_m["reward_margin"] > 0.0


def test_teacher_relabeling_and_dagger_formatting_on_synthetic_step_history() -> None:
    env_ref = Env(tier="easy", seed=104_500)
    instruction = env_ref.instruction()
    tools_spec = env_ref.tools_spec()
    emps = [{"id": f"e{i:02d}", "name": f"Emp{i}", "dept": "Engineering", "role": "engineer"} for i in range(12)]

    t0_tool, t0_args, _ = mod.relabel_student_state_with_solver("easy", instruction, tools_spec, [])
    assert (t0_tool, t0_args) == ("list_employees", {})

    synthetic_accuse_hist = [
        Step(t=0, day=1, tool="list_employees", args={}, result={"ok": True, "data": {"employees": emps}}),
        Step(
            t=1,
            day=1,
            tool="status",
            args={},
            result={"ok": True, "data": {"day": 1, "V": 1.0, "actions_left_today": 8, "restricted": []}},
        ),
        Step(
            t=2,
            day=1,
            tool="list_documents",
            args={"day_from": 1, "day_to": 1},
            result={"ok": True, "data": {"documents": []}},
        ),
        Step(
            t=3,
            day=1,
            tool="plant_canary",
            args={
                "doc_title": "Memo 1",
                "assignment": {"e00": "A", "e01": "A", "e02": "B", "e03": "C"},
            },
            result={"ok": True, "data": {"canary_id": "c1", "day": 1}},
        ),
        Step(t=4, day=1, tool="advance_day", args={}, result={"ok": True, "data": {"day": 2, "V": 0.94}}),
        Step(
            t=5,
            day=2,
            tool="status",
            args={},
            result={"ok": True, "data": {"day": 2, "V": 0.94, "actions_left_today": 8, "restricted": []}},
        ),
        Step(
            t=6,
            day=2,
            tool="list_documents",
            args={"day_from": 1, "day_to": 2},
            result={
                "ok": True,
                "data": {
                    "documents": [
                        {
                            "doc_id": "c1",
                            "day": 1,
                            "title": "Memo 1",
                            "is_canary": True,
                            "recipients": ["e00", "e01", "e02", "e03"],
                            "variants": {"A": ["e00", "e01"], "B": ["e02"], "C": ["e03"]},
                        }
                    ]
                },
            },
        ),
        Step(
            t=7,
            day=2,
            tool="check_leak_feed",
            args={},
            result={"ok": True, "data": {"items": [{"doc_id": "c1", "variant": "C", "surfaced_day": 2}]}},
        ),
        Step(
            t=8,
            day=2,
            tool="read_access_logs",
            args={"day_from": 1, "day_to": 1},
            result={"ok": True, "data": {"logs": []}},
        ),
    ]

    t_tool, t_args, t_meta = mod.relabel_student_state_with_solver(
        tier="easy",
        instruction=instruction,
        tools_spec=tools_spec,
        history_prefix=synthetic_accuse_hist,
    )
    assert t_tool == "accuse"
    assert t_args == {"employee": "e03"}
    assert t_meta["top_p"] > 0.95
    assert t_meta["ev_accuse"] > 0.5

    dag_disagree, reps_disagree = mod.build_compact_dagger_record(
        tier="easy",
        seed=104_500,
        instruction=instruction,
        tools_spec=tools_spec,
        history_prefix=synthetic_accuse_hist,
        student_tool="advance_day",
        student_args={},
        step_ok=True,
        tail_turns=4,
    )
    assert dag_disagree["disagree"] is True
    assert dag_disagree["target_tool"] == "accuse"
    assert dag_disagree["student_tool"] == "advance_day"
    assert reps_disagree == 4
    assert "CONSISTENT_SUSPECTS(1): [e03]" in dag_disagree["messages"][1]["content"]
    tc_fn = dag_disagree["messages"][-1]["tool_calls"][0]["function"]
    assert tc_fn["name"] == "accuse"

    dag_agree, reps_agree = mod.build_compact_dagger_record(
        tier="easy",
        seed=104_500,
        instruction=instruction,
        tools_spec=tools_spec,
        history_prefix=synthetic_accuse_hist,
        student_tool="accuse",
        student_args={"employee": "e03"},
        step_ok=True,
        tail_turns=4,
    )
    assert dag_agree["disagree"] is False
    assert reps_agree == 1

    with pytest.raises(ValueError, match="HELDOUT_SEEDS"):
        mod.build_compact_dagger_record(
            tier="easy",
            seed=800_000,
            instruction=instruction,
            tools_spec=tools_spec,
            history_prefix=synthetic_accuse_hist,
            student_tool="status",
            student_args={},
        )

    synthetic_horizon_hist = [
        Step(t=0, day=1, tool="list_employees", args={}, result={"ok": True, "data": {"employees": emps}}),
        Step(t=1, day=13, tool="advance_day", args={}, result={"ok": True, "data": {"day": 14, "V": 1.0}}),
        Step(
            t=2,
            day=14,
            tool="status",
            args={},
            result={"ok": True, "data": {"day": 14, "V": 1.0, "actions_left_today": 8, "restricted": []}},
        ),
        Step(
            t=3,
            day=14,
            tool="list_documents",
            args={"day_from": 11, "day_to": 14},
            result={"ok": True, "data": {"documents": []}},
        ),
        Step(t=4, day=14, tool="check_leak_feed", args={}, result={"ok": True, "data": {"items": []}}),
        Step(
            t=5,
            day=14,
            tool="read_access_logs",
            args={"day_from": 13, "day_to": 13},
            result={"ok": True, "data": {"logs": []}},
        ),
    ]
    h_tool, h_args, h_meta = mod.relabel_student_state_with_solver(
        tier="easy",
        instruction=instruction,
        tools_spec=tools_spec,
        history_prefix=synthetic_horizon_hist,
    )
    assert (h_tool, h_args) == ("advance_day", {})
    assert h_meta["top_p"] < h_meta["breakeven_p"]
    assert h_meta["ev_accuse"] < 0.0


def test_compact_lora_policy_stub_episode_and_replay_verification(tmp_path: Path) -> None:
    secret = mod.HELDOUT_SECRET_DEFAULT
    sec_tag = mod.compute_world_secret_tag(secret)
    assert sec_tag == "sha256:ebf2f09716cf76d3"

    step_counter = {"n": 0}

    def _stub_gen(turn: dict[str, Any]) -> str:
        assert "messages" in turn and "tools" in turn
        step_counter["n"] += 1
        k = step_counter["n"]
        if k == 1:
            return '<tool_call>\n{"name": "list_employees", "arguments": {}}\n</tool_call>'
        if k == 2:
            return "not valid json tool output"
        if k == 3:
            return '<tool_call>\n{"name": "check_leak_feed", "arguments": {}}\n</tool_call>'
        return '<tool_call>\n{"name": "advance_day", "arguments": {}}\n</tool_call>'

    with mod.scoped_world_secret(secret):
        env = Env(tier="easy", seed=800_000)
        pol = mod.CompactLoRAPolicy(name="stub_qwen05b", kv_reuse=False, generator=_stub_gen, tail_turns=3)
        pol.reset(env.tools_spec(), env.instruction())
        pol.set_prefetched_text('<tool_call>\n{"name": "status", "arguments": {}}\n</tool_call>')
        first_tool, first_args = pol.act(list(env.history))
        assert (first_tool, first_args) == ("status", {})
        env.call(first_tool, first_args)

        while not env.done:
            t_name, t_args = pol.act(list(env.history))
            env.call(t_name, t_args)
        ep = env.result(pol.name)

    assert pol.invalid == 1
    assert ep.end_reason == "horizon"
    assert ep.score == 0.0
    assert ep.correct is False

    raw_ep = dataclasses.asdict(ep)
    raw_ep["meta"] = {**dict(raw_ep.get("meta") or {}), "world_secret_tag": sec_tag, "invalid_calls": pol.invalid}
    verified_ep = mod.verify_episode(raw_ep, world_secret=secret)
    assert verified_ep["meta"]["replay_verified"] is True

    tampered = dict(verified_ep)
    tampered["score"] = 0.75
    with pytest.raises(ValueError, match="replay score mismatch"):
        mod.verify_episode(tampered, world_secret=secret)

    ep_file = tmp_path / "stub_episodes.jsonl"
    ep_file.write_text(json.dumps(verified_ep) + "\n", encoding="utf-8")
    f_rep = mod.verify_compact_episode_file(ep_file, world_secret=secret)
    assert f_rep["replay_ok"] is True
    assert f_rep["data_rule_clean"] is True
    assert f_rep["valid_count"] == 1
    assert f_rep["world_secret_tag"] == sec_tag

    hf_rep = verify_episode_file(ep_file, world_secret=secret)
    assert hf_rep["replay_ok"] is True
    assert hf_rep["excluded_count"] == 0

    with mod.scoped_world_secret(secret):
        env2 = Env(tier="easy", seed=800_001)
        pol2 = mod.CompactLoRAPolicy(
            name="stub_runner",
            generator=lambda _t: '<tool_call>\n{"name": "advance_day", "arguments": {}}\n</tool_call>',
        )
        ep2 = run_episode(env2, pol2, max_iters=30)
    assert ep2.end_reason == "horizon"
    assert mod.verify_episode(dataclasses.asdict(ep2), world_secret=secret)["meta"]["replay_verified"] is True


def test_tiny_end_to_end_cli_pipeline_and_provenance(tmp_path: Path) -> None:
    out_dir = tmp_path / "qwen05b_tiny"
    sum_path = tmp_path / "summary.json"
    tbl_path = tmp_path / "table.md"

    t0 = time.perf_counter()
    res = mod.main([
        "--tiny",
        "--all",
        "--out-dir",
        str(out_dir),
        "--out-summary",
        str(sum_path),
        "--out-table",
        str(tbl_path),
    ])
    elapsed = time.perf_counter() - t0
    assert elapsed < 10.0
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    summary = res["eval"]
    assert sum_path.is_file()
    assert tbl_path.is_file()
    assert not list(tmp_path.rglob("*.safetensors"))
    assert not list(tmp_path.rglob("*.pt"))
    assert not list(tmp_path.rglob("*.bin"))

    exp_tag = mod.compute_world_secret_tag(mod.HELDOUT_SECRET_DEFAULT)
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["world_secret_tag"] == exp_tag
    assert summary["before"]["world_secret_tag"] == exp_tag
    assert summary["after"]["world_secret_tag"] == exp_tag
    assert all(s in TRAIN_SEEDS for s in summary["train_seeds"])
    e_start, e_stop = summary["eval_seeds"]["start"], summary["eval_seeds"]["stop"]
    assert all(s in HELDOUT_SEEDS for s in range(e_start, e_stop))

    errs: list[str] = []
    checked = gate._audit_generic_summary_table(tbl_path, sum_path, errs)
    assert errs == []
    assert checked == 4

    led_res = ledger_mod.validate_experiment_summary(summary, str(sum_path))
    assert led_res["gates"]["gate1_seed_hygiene"] is True
    assert led_res["gates"]["gate2_paired_world_secret"] is True

    add_entry = addendum_mod.evaluate_run_summary(summary, summary_path=str(sum_path), repo_root=REPO_ROOT)
    assert add_entry["track"] == "track_1"
    assert add_entry["family"] == "Qwen2.5-0.5B"
    assert add_entry["is_open_weight_llm"] is True
    assert add_entry["criteria"]["autonomous_inference"] is True
    assert add_entry["criteria"]["train_eval_disjoint"] is True
    assert "train/compact_lora_sft.py" in add_entry["inference_modules_checked"]
    assert "train/compact_lora_sft.py:CompactLoRAPolicy" in add_entry["inference_policy_classes"]


def test_export_manifest_dpo_dagger_and_shared_or_temp_smoke(tmp_path: Path) -> None:
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    assert COMMITTED_MANIFEST_PATH.is_file()
    assert COMMITTED_MANIFEST_PATH.stat().st_size < 65_536
    assert not (COMMITTED_MANIFEST_PATH.parent / "summary.json").exists()
    assert not (COMMITTED_MANIFEST_PATH.parent / "table.md").exists()

    raw_mf = COMMITTED_MANIFEST_PATH.read_text(encoding="utf-8")
    assert em_dash not in raw_mf
    assert en_dash not in raw_mf
    manifest = json.loads(raw_mf)

    assert manifest["tiers"] == ["easy", "medium", "hard"]
    assert manifest["tail_turns"] == 4
    assert manifest["workers"] == 1
    mod.assert_all_splits_disjoint(
        list(manifest["train_seeds"]),
        list(manifest["val_seeds"]),
        list(range(800_000, 800_030)),
        list(range(0, 30)),
    )

    tr_split = manifest["splits"]["train"]
    va_split = manifest["splits"]["val"]
    assert tr_split["sft_turns"] == 10_004
    assert tr_split["dpo_pairs"] == 951
    assert va_split["sft_turns"] == 1_593
    assert va_split["dpo_pairs"] == 200
    assert set(tr_split["dpo_pair_distribution"]) == {
        "premature_accuse",
        "wrong_target_accuse",
        "stall_when_ev_pos",
    }
    assert sum(int(v["sft_turns_written"]) for v in tr_split["tiers"].values()) == tr_split["sft_turns"]
    assert sum(int(v["dpo_pairs_written"]) for v in tr_split["tiers"].values()) == tr_split["dpo_pairs"]
    assert sum(int(v["sft_turns_written"]) for v in va_split["tiers"].values()) == va_split["sft_turns"]
    assert sum(int(v["dpo_pairs_written"]) for v in va_split["tiers"].values()) == va_split["dpo_pairs"]

    shared_mf = SHARED_EXPORT_DIR / "export_manifest.json"
    shared_files_ok = all(
        (SHARED_EXPORT_DIR / fname).is_file()
        for fname in (
            "export_manifest.json",
            "compact_sft_train.jsonl",
            "compact_sft_val.jsonl",
            "compact_dpo_train.jsonl",
            "compact_dpo_val.jsonl",
        )
    )

    smoke_dir = tmp_path / "compact_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    if shared_files_ok:
        shared_data = json.loads(shared_mf.read_text(encoding="utf-8"))
        assert shared_data == manifest
        reused_mf = mod.export_compact_datasets(
            out_dir=SHARED_EXPORT_DIR,
            tiers=("easy", "medium", "hard"),
            tail_turns=4,
            workers=1,
            reuse_existing=True,
        )
        assert reused_mf["splits"]["train"]["sft_turns"] == 10_004
        for fname, limit_n in (
            ("compact_sft_train.jsonl", 8),
            ("compact_sft_val.jsonl", 4),
            ("compact_dpo_train.jsonl", 6),
            ("compact_dpo_val.jsonl", 4),
        ):
            src_file = SHARED_EXPORT_DIR / fname
            lines: list[str] = []
            with open(src_file, "r", encoding="utf-8") as fh:
                for _ in range(limit_n):
                    ln = fh.readline()
                    if not ln:
                        break
                    lines.append(ln)
            (smoke_dir / fname).write_text("".join(lines), encoding="utf-8")
    else:
        mod.export_compact_datasets(
            out_dir=smoke_dir,
            tiers=("easy",),
            n_train=1,
            n_augment=1,
            n_val=1,
            n_val_augment=0,
            tail_turns=4,
            workers=1,
            reuse_existing=False,
        )

    tok = _DeterministicMockTokenizer()
    sft_sample = json.loads((smoke_dir / "compact_sft_train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    dpo_sample = json.loads((smoke_dir / "compact_dpo_train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert mod.pack_compact_turn_ids(sft_sample, tok, max_len=2560) is not None
    assert mod.pack_compact_dpo_pair_ids(dpo_sample, tok, max_len=2560) is not None

    sft_sum = mod.train_sft_stage(
        model_path=str(tmp_path / "no_local_weights"),
        out_dir=smoke_dir,
        max_steps=2,
        tiny=True,
    )
    assert sft_sum["device"] == "cpu_tiny_stub"
    assert sft_sum["best_val_loss"] < sft_sum["init_val_loss"]

    dpo_sum = mod.train_dpo_stage(
        model_path=str(tmp_path / "no_local_weights"),
        out_dir=smoke_dir,
        max_steps=2,
        tiny=True,
    )
    assert dpo_sum["device"] == "cpu_tiny_stub"
    assert dpo_sum["best_val_dpo_loss"] < dpo_sum["init_val"]["val_dpo_loss"]

    dag_sum = mod.train_dagger_stage(
        model_path=str(tmp_path / "no_local_weights"),
        out_dir=smoke_dir,
        tiers=("easy",),
        dagger_seed_start=104_500,
        dagger_per_tier=1,
        steps=2,
        max_rollout_steps=4,
        tiny=True,
    )
    assert dag_sum["device"] == "cpu_tiny_stub"
    assert dag_sum["visited_states"] >= 1
    assert dag_sum["disagreements"] >= 1
    assert not list(smoke_dir.rglob("*.safetensors"))
    assert not list(smoke_dir.rglob("*.bin"))
    assert not list(smoke_dir.rglob("*.pt"))
