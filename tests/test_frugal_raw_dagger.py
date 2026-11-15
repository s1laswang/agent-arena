from __future__ import annotations

import ast
import io
import json
import os
from pathlib import Path
import sys
import time
import tokenize
import types

import pytest

from canary.env import Env
from canary.rules import HELDOUT_SEEDS, TIERS, TRAIN_SEEDS
from canary.types import Step
import scripts.tiebreak_addendum_pack as addendum
import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.verify_tiebreak_submission as gate
import train.frugal_raw_dagger as mod

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "train" / "frugal_raw_dagger.py"
SELF_PATH = Path(__file__).resolve()
ARTIFACT_DIR = REPO_ROOT / "results" / "tiebreak" / "frugal_raw_dagger"


def test_source_hygiene_and_ast_inference_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    banned_top_imports = {"torch", "transformers", "peft"}
    banned_any_top = {"canary.world", "canary.solver"}

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
                    assert not any(alias.name.startswith(b) for b in banned_any_top)
            elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                assert stmt.module.split(".")[0] not in banned_top_imports
                assert not any(stmt.module.startswith(b) for b in banned_any_top)

    ast_res = gate.check_ast_inference_isolation(
        root=REPO_ROOT,
        extra_paths=[MODULE_PATH],
        strict=True,
    )
    assert ast_res.passed is True, ast_res.errors
    assert "train/frugal_raw_dagger.py:RawFrugalHFPolicy" in ast_res.metrics["policy_classes_checked"]
    add_errs, add_classes = addendum.audit_inference_module_ast("train/frugal_raw_dagger.py", MODULE_PATH)
    assert add_errs == []
    assert "train/frugal_raw_dagger.py:RawFrugalHFPolicy" in add_classes
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    replies = iter([
        '<tool_call>\n{"name": "check_leak_feed", "arguments": {}}\n</tool_call>',
        "not a valid tool call payload",
    ])
    with mod.world_secret_scope(mod.HELDOUT_SECRET):
        env = Env(tier="easy", seed=800_000)
        pol = mod.RawFrugalHFPolicy(
            name="unit_raw_frugal",
            max_ctx=4000,
            max_new=80,
            kv_reuse=False,
            generator=lambda _h: next(replies),
        )
        pol.reset(env.tools_spec(), env.instruction())
        t1, a1 = pol.act(env.history)
        assert (t1, a1) == ("check_leak_feed", {})
        assert pol.invalid == 0
        env.call(t1, a1)
        t2, a2 = pol.act(env.history)
        assert (t2, a2) == ("status", {})
        assert pol.invalid == 1
        assert pol.calls == 2


def test_parse_vis_state_public_history_and_mid_episode_drop() -> None:
    env = Env(tier="easy", seed=110_000)
    params = TIERS["easy"]

    r_can = env.call("plant_canary", {"doc_title": "c1", "assignment": {"e00": "A", "e01": "B"}})
    assert r_can.ok is True
    r_res = env.call("restrict_access", {"employee": "e02"})
    assert r_res.ok is True
    r_bad = env.call("restrict_access", {"employee": "e02"})
    assert r_bad.ok is False

    vs_day1 = mod.parse_vis_state(list(env.history), params)
    assert len(vs_day1.emps) == params.n_employees
    assert vs_day1.today == 1
    assert vs_day1.can_today == 1
    assert vs_day1.used_today == {"e00", "e01"}
    assert vs_day1.restricted == {"e02"}
    assert vs_day1.actions_today == 2
    assert "c1" in vs_day1.docs
    assert vs_day1.docs["c1"]["is_canary"] is True
    assert vs_day1.docs["c1"]["variants"] == {"e00": "A", "e01": "B"}

    env.call("advance_day", {})
    env.call("check_leak_feed", {})
    env.call("list_documents", {"day_from": 1, "day_to": 2})
    env.call("unrestrict_access", {"employee": "e02"})

    vs_day2 = mod.parse_vis_state(list(env.history), params)
    assert vs_day2.today == 2
    assert vs_day2.can_today == 0
    assert vs_day2.checked_feed_today is True
    assert vs_day2.listed_this_day == 1
    assert vs_day2.listed_days == {1, 2}
    assert vs_day2.restricted == set()
    assert vs_day2.docs["c1"]["variants"] == {"e00": "A", "e01": "B"}

    sliced = list(env.history)[4:]
    assert sliced[0].day == 2
    vs_sliced = mod.parse_vis_state(sliced, params)
    assert vs_sliced.today == 2
    assert vs_sliced.checked_feed_today is True
    assert vs_sliced.listed_days == {1, 2}


def test_frugal_4000_token_window_construction_and_weights() -> None:
    tok = mod.SyntheticChatTokenizer(vocab_size=4096)
    sample_txt = '<tool_call>\n{"name": "accuse", "arguments": {"employee": "e03"}}\n</tool_call>'
    assert tok.decode(tok.encode_text(sample_txt)) == sample_txt

    tcache = mod.FastTemplateCache(tok)
    windows, stats = mod.collect_sft_data(
        tcache,
        specs=[("easy", 110_000), ("medium", 110_001)],
        max_ctx=4000,
        max_new=80,
        max_calls=45,
    )
    assert stats["episodes"] == 2
    assert stats["windows"] >= 2
    assert len(windows) == stats["windows"]

    env_e = Env(tier="easy", seed=110_000)
    h0, gsuf = tcache.header(env_e.instruction(), mod.to_openai_tools(env_e.tools_spec()))
    assert len(h0) < 4000 - 80

    saw_weighted = False
    for inp, lab, wts in windows:
        assert len(inp) == len(lab) == len(wts)
        assert len(inp) <= 4000
        assert all(x == mod.IGNORE_INDEX for x in lab[:len(h0)])
        sup_positions = [i for i, y in enumerate(lab) if y != mod.IGNORE_INDEX]
        assert len(sup_positions) > 0
        for pos in sup_positions:
            assert lab[pos] == inp[pos]
            if wts[pos] > 1.0:
                saw_weighted = True
    assert saw_weighted is True

    tight_ctx = len(h0) + len(gsuf) + 180
    tight_windows, tight_stats = mod.collect_sft_data(
        tcache,
        specs=[("easy", 110_002)],
        max_ctx=tight_ctx,
        max_new=40,
        max_calls=12,
    )
    assert tight_stats["turns"] >= 4
    assert len(tight_windows) >= 2
    assert all(len(w[0]) <= tight_ctx for w in tight_windows)

    for _ in range(3):
        t_act, a_act = mod.frugal_teacher_action("easy", list(env_e.history))
        env_e.call(t_act, a_act)
    pair_chunks = [tcache.pair_ids(st) for st in env_e.history]
    trace = [
        (0, 0, "plant_canary", {"doc_title": "c1", "assignment": {"e00": "A", "e01": "B"}}, False),
        (1, 0, "advance_day", {}, True),
        (2, 0, "check_leak_feed", {}, False),
    ]
    dag_wins = mod._segment_dagger_trace(h0, gsuf, pair_chunks, trace, tcache, tok.eos_token_id, 4000)
    assert len(dag_wins) == 2
    assert all(len(w[0]) <= 4000 for w in dag_wins)


def test_teacher_relabeling_on_public_step_history() -> None:
    env = Env(tier="medium", seed=110_010)
    ins = env.instruction()
    for _ in range(6):
        public_copy = [
            Step(
                t=st.t,
                day=st.day,
                tool=st.tool,
                args=dict(st.args),
                result=json.loads(json.dumps(st.result)),
            )
            for st in env.history
        ]
        t_frug, a_frug = mod.relabel_public_steps("medium", public_copy, instruction=ins, use_solver_posterior=False)
        t_solv, a_solv = mod.relabel_public_steps("medium", public_copy, instruction=ins, use_solver_posterior=True)
        assert isinstance(t_frug, str) and isinstance(a_frug, dict)
        assert isinstance(t_solv, str) and isinstance(a_solv, dict)
        res = env.call(t_frug, a_frug)
        assert res.ok is True

    cap_env = Env(tier="easy", seed=110_011)
    cap_env.call("restrict_access", {"employee": "e00"})
    t_can, a_can = mod.frugal_teacher_action("easy", list(cap_env.history))
    if t_can == "plant_canary":
        assert "e00" not in a_can["assignment"]
    while cap_env._actions_today < cap_env.p.actions_per_day:
        r = cap_env.call("check_leak_feed", {})
        assert r.ok is True
    t_after_cap, a_after_cap = mod.relabel_public_steps(
        "easy",
        list(cap_env.history),
        instruction=cap_env.instruction(),
        use_solver_posterior=True,
    )
    assert cap_env.call(t_after_cap, a_after_cap).ok is True


def test_seed_hygiene_guards_and_rejections() -> None:
    plan = mod.validate_seed_plan(
        range(110_000, 110_240),
        range(110_240, 110_360),
        range(800_000, 800_030),
        world_secret=mod.HELDOUT_SECRET,
    )
    assert len(plan["sft"]) == 240
    assert len(plan["dagger"]) == 120
    assert len(plan["train_all"]) == 360
    assert len(plan["eval"]) == 30
    assert all(s in TRAIN_SEEDS for s in plan["train_all"])
    assert all(s in HELDOUT_SEEDS for s in plan["eval"])
    assert set(plan["train_all"]).isdisjoint(plan["eval"])
    assert plan["world_secret_tag"] == "sha256:ebf2f09716cf76d3"

    for bad_sft, bad_dag, bad_eval, bad_sec, match_txt in (
        ([0], [110_240], [800_000], mod.HELDOUT_SECRET, "outside TRAIN_SEEDS"),
        ([800_000], [110_240], [800_001], mod.HELDOUT_SECRET, "outside TRAIN_SEEDS"),
        ([900_000], [110_240], [800_000], mod.HELDOUT_SECRET, "outside TRAIN_SEEDS"),
        ([110_000], [900_500], [800_000], mod.HELDOUT_SECRET, "outside TRAIN_SEEDS"),
        ([110_000], [110_000], [800_000], mod.HELDOUT_SECRET, "pairwise disjoint"),
        ([110_000], [110_240], [0], mod.HELDOUT_SECRET, "outside HELDOUT_SEEDS"),
        ([110_000], [110_240], [110_500], mod.HELDOUT_SECRET, "outside HELDOUT_SEEDS"),
        ([110_000], [110_240], [800_200], mod.HELDOUT_SECRET, "outside HELDOUT_SEEDS"),
        ([110_000], [110_240], [900_000], mod.HELDOUT_SECRET, "outside HELDOUT_SEEDS"),
        ([110_000], [110_240], [800_000], "unset", "world_secret"),
        ([110_000], [110_240], [800_000], "short", "world_secret"),
    ):
        with pytest.raises(ValueError, match=match_txt):
            mod.validate_seed_plan(bad_sft, bad_dag, bad_eval, world_secret=bad_sec)

    tcache = mod.FastTemplateCache(mod.SyntheticChatTokenizer())
    for forbidden_seed in (0, 800_000, 900_000):
        with pytest.raises(ValueError, match="non-train seed"):
            mod.collect_sft_data(tcache, [("easy", forbidden_seed)], max_calls=2)
        with pytest.raises(ValueError, match="non-train seed"):
            mod._run_pure_python_tiny_episodes(
                tcache,
                [("easy", forbidden_seed)],
                agent_name="bad_dagger",
                raw_reply="x",
                max_ctx=4000,
                max_new=8,
                max_calls=1,
                collect_dagger=True,
            )


def test_tiny_and_synthetic_qwen2config_smoke_in_tmp_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synth_tok = mod.SyntheticChatTokenizer(vocab_size=4096)
    cfg_kwargs = mod.build_tiny_qwen2_config_kwargs(synth_tok)
    assert cfg_kwargs["hidden_size"] == 32
    assert cfg_kwargs["num_hidden_layers"] == 1
    assert cfg_kwargs["max_position_embeddings"] == 4096
    assert cfg_kwargs["vocab_size"] >= 4096

    called_pretrained: list[str] = []
    captured_cfg: dict[str, object] = {}

    fake_torch = types.ModuleType("torch")
    fake_torch.float16 = "float16"
    fake_torch.float32 = "float32"
    fake_torch.set_num_threads = lambda _n: None
    fake_torch.manual_seed = lambda _s: None
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)

    class _FakeQwen2Config:
        def __init__(self, **kw: object) -> None:
            captured_cfg.update(kw)

    class _FakeQwen2ForCausalLM:
        def __init__(self, cfg: _FakeQwen2Config) -> None:
            self.cfg = cfg
            self.device = "cpu"

        def to(self, dev: str) -> "_FakeQwen2ForCausalLM":
            self.device = dev
            return self

        def eval(self) -> "_FakeQwen2ForCausalLM":
            return self

    class _FakeAutoModel:
        @staticmethod
        def from_pretrained(path: str, **_kw: object) -> None:
            called_pretrained.append(path)
            raise AssertionError("full 1.5B weights must never load in tiny mode")

    class _FakeAutoTok:
        @staticmethod
        def from_pretrained(_path: str, **_kw: object) -> mod.SyntheticChatTokenizer:
            return mod.SyntheticChatTokenizer(vocab_size=4096)

    fake_tr = types.ModuleType("transformers")
    fake_tr.AutoModelForCausalLM = _FakeAutoModel
    fake_tr.AutoTokenizer = _FakeAutoTok
    fake_tr.Qwen2Config = _FakeQwen2Config
    fake_tr.Qwen2ForCausalLM = _FakeQwen2ForCausalLM

    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "torch", fake_torch)
        mp.setitem(sys.modules, "transformers", fake_tr)
        tiny_model, tiny_tok = mod.load_base_and_tokenizer(str(tmp_path / "missing_model_dir"), tiny=True)
        assert isinstance(tiny_model, _FakeQwen2ForCausalLM)
        assert isinstance(tiny_tok, mod.SyntheticChatTokenizer)
        assert called_pretrained == []
        assert captured_cfg["hidden_size"] == 32

    prev_secret = os.environ.get("CANARY_WORLD_SECRET")
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    t0 = time.perf_counter()
    with monkeypatch.context() as mp:
        mp.setattr(mod, "_has_ml_stack", lambda: False)
        rc = mod.main([
            "--tiny",
            "--out-dir",
            str(out_dir),
            "--work-dir",
            str(work_dir),
        ])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 8.0
    assert os.environ.get("CANARY_WORLD_SECRET") == prev_secret
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    summary_path = out_dir / "summary.json"
    table_path = out_dir / "table.md"
    assert summary_path.is_file()
    assert table_path.is_file()
    assert summary_path.stat().st_size <= 120 * 1024

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"] == "qwen15b-raw-dagger-v14"
    assert summary["n"] == 3
    assert summary["tiers"] == ["easy", "medium", "hard"]
    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["before"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["after"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["training"]["sft_r0"]["windows"] >= 3
    assert summary["training"]["dagger_r1"]["relabeled_states"] >= 3
    assert summary["training"]["dagger_r1"]["windows"] >= 3

    for fname in ("before_episodes.jsonl", "after_episodes.jsonl"):
        rep = mod.verify_episodes_jsonl(
            work_dir / fname,
            max_calls=2,
            world_secret=mod.HELDOUT_SECRET,
        )
        assert rep["replay_verified"] is True
        assert rep["invalid_episodes"] == 0
        assert rep["episodes"] == 3

    table_errs: list[str] = []
    checked = gate._audit_generic_summary_table(table_path, summary_path, table_errs)
    assert table_errs == []
    assert checked == 4

    led_res = ledger_mod.validate_experiment_summary(summary, str(summary_path))
    assert led_res["gates"]["gate1_seed_hygiene"] is True
    assert led_res["gates"]["gate2_paired_world_secret"] is True

    add_res = addendum.evaluate_run_summary(summary, str(summary_path), repo_root=REPO_ROOT)
    assert add_res["track"] == "track_1"
    assert add_res["family"] == "Qwen2.5-1.5B"
    assert add_res["is_open_weight_llm"] is True
    assert add_res["criteria"]["train_eval_disjoint"] is True
    assert add_res["criteria"]["autonomous_inference"] is True


def test_committed_artifact_if_present() -> None:
    summary_path = ARTIFACT_DIR / "summary.json"
    table_path = ARTIFACT_DIR / "table.md"
    if not summary_path.is_file() and not table_path.is_file():
        return

    assert summary_path.is_file()
    assert table_path.is_file()
    assert summary_path.stat().st_size <= 120 * 1024
    md_txt = table_path.read_text(encoding="utf-8")
    assert chr(0x2014) not in md_txt
    assert chr(0x2013) not in md_txt

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["run_id"] == "qwen15b-raw-dagger-v14"
    assert data["n"] == 90
    assert data["tiers"] == ["easy", "medium", "hard"]
    assert data["replay_verified"] is True
    assert data["invalid_episodes"] == 0
    assert data["before"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert data["after"]["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert len(data["paired"]["deltas"]) == 90

    errs: list[str] = []
    checked = gate._audit_generic_summary_table(table_path, summary_path, errs)
    assert errs == []
    assert checked == 4
