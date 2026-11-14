from __future__ import annotations

import ast
import importlib.util
import json
import math
import random
from pathlib import Path

import pytest

from canary.mole.dsl import MoleDoc, MoleView
import train.grpo_mole as grpo_mole
import train.qwen_diverse_mole as qdm

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "train" / "qwen_diverse_mole.py"


def _sample_mole_view_dict(
    *,
    day: int = 2,
    restricted: bool = False,
    can_leak: bool = True,
    docs: list[dict] | None = None,
) -> dict:
    if docs is None:
        docs = [
            {"doc_id": "d1", "title": "Team sync", "recipient_count": 6, "age_days": 2},
            {"doc_id": "d2", "title": "All hands memo", "recipient_count": 20, "age_days": 1},
            {"doc_id": "d3", "title": "Launch brief", "recipient_count": 12, "age_days": 0},
        ]
    return {
        "day": day,
        "days_since_last_leak": 1,
        "i_am_restricted": restricted,
        "n_restricted_colleagues": 1,
        "recent_low_recipient_docs": 1,
        "peers": ["e01", "e02", "e03", "e04"],
        "restricted_peers": ["e03"],
        "decoy": "e04",
        "can_leak": can_leak,
        "held_docs": docs,
    }


def test_lazy_imports_and_grpo_prompt_compatibility():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden = {"torch", "transformers", "peft"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden

    assert qdm.SYSTEM is grpo_mole.SYSTEM
    assert qdm.render_view is grpo_mole.render_view

    v = MoleView(
        day=3,
        docs=(MoleDoc("d1", "Memo", 14, 1),),
        days_since_last_leak=2,
        i_am_restricted=0,
        n_restricted_colleagues=1,
        recent_low_recipient_docs=0,
        peers=("e01", "e02"),
        restricted_peers=("e02",),
        decoy="e01",
        can_leak=True,
    )
    mv_dict = {
        "day": 3,
        "held_docs": [{"doc_id": "d1", "title": "Memo", "recipient_count": 14, "age_days": 1}],
        "days_since_last_leak": 2,
        "i_am_restricted": False,
        "n_restricted_colleagues": 1,
        "recent_low_recipient_docs": 0,
        "peers": ["e01", "e02"],
        "restricted_peers": ["e02"],
        "decoy": "e01",
        "can_leak": True,
    }
    assert qdm.render_dict_view(mv_dict) == grpo_mole.render_view(v)


def test_extract_sft_mapping_none_cap_and_seed_guard(tmp_path):
    mv = _sample_mole_view_dict()
    assert qdm.map_carbon_turn({"mole_view": mv, "leak": "d2", "frame": "e04"}) == (
        "most_recipients",
        "decoy",
        False,
    )
    assert qdm.map_carbon_turn({"mole_view": mv, "leak": "d3", "frame": "e03"}) == (
        "newest",
        "most_restricted_peer",
        False,
    )
    assert qdm.map_carbon_turn({"mole_view": mv, "leak": "d1", "frame": "e01"}) == (
        "oldest",
        "random_peer",
        False,
    )
    trap_mv = _sample_mole_view_dict(
        restricted=True,
        docs=[{"doc_id": "c1", "title": "Trap canary", "recipient_count": 4, "age_days": 0}],
    )
    assert qdm.map_carbon_turn({"mole_view": trap_mv, "leak": None, "frame": None}) == (
        "none",
        "none",
        True,
    )

    jdir = tmp_path / "carbon_jsonl"
    jdir.mkdir()
    lines = []
    for i in range(20):
        lines.append(
            json.dumps(
                {
                    "seed": i % 6,
                    "day": (i % 5) + 1,
                    "tier": "hard",
                    "leak": "d2" if i % 2 == 0 else "d3",
                    "frame": "e04" if i % 3 == 0 else "e03",
                    "error": None,
                    "mole_view": mv,
                }
            )
        )
    for i in range(6):
        lines.append(
            json.dumps(
                {
                    "seed": 1,
                    "day": i + 1,
                    "tier": "hard",
                    "leak": None,
                    "frame": None,
                    "error": None,
                    "mole_view": mv,
                }
            )
        )
    for i in range(10):
        lines.append(
            json.dumps(
                {
                    "seed": 2,
                    "day": i + 1,
                    "tier": "hard",
                    "leak": None,
                    "frame": None,
                    "error": None,
                    "mole_view": trap_mv,
                }
            )
        )
    (jdir / "mole_decisions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_sft = tmp_path / "sft.jsonl"
    meta = qdm.main(
        [
            "extract-sft",
            "--jsonl-dir",
            str(jdir),
            "--max-none-share",
            "0.15",
            "--n-counterfactual",
            "1",
            "--tier",
            "easy",
            "--seed-base",
            "120000",
            "--workers",
            "1",
            "--out",
            str(out_sft),
        ]
    )
    saved = [json.loads(x) for x in out_sft.read_text(encoding="utf-8").splitlines() if x.strip()]
    carbon_saved = [r for r in saved if r["source"] == "gemini-4-carbon"]
    none_rows = [r for r in carbon_saved if r["action"][0] == "none"]
    assert len(carbon_saved) == 23
    assert len(none_rows) == 3
    assert all(r["trap_only"] is True for r in none_rows)
    assert len(none_rows) / len(carbon_saved) <= 0.15
    assert meta["carbon_none_share"] <= 0.15

    git_rows = qdm.extract_carbon_sft(repo=ROOT, max_none_share=0.15)
    if git_rows:
        git_none = [r for r in git_rows if r["action"][0] == "none"]
        assert all(r["trap_only"] is True for r in git_none)
        assert len(git_none) / len(git_rows) <= 0.15

    for bad_seed in (-1, 195_000, 200_000, 400_000, 800_000, 900_000):
        with pytest.raises(ValueError):
            qdm.guard_train_seed(bad_seed)
        with pytest.raises(ValueError):
            qdm.guard_counterfactual_seed(bad_seed)

    for non_cf_seed in (0, 5, 100_000, 119_999):
        with pytest.raises(ValueError):
            qdm.guard_counterfactual_seed(non_cf_seed)

    bad_dir = tmp_path / "bad_jsonl"
    bad_dir.mkdir()
    (bad_dir / "leak.jsonl").write_text(
        json.dumps({"seed": 900_000, "day": 1, "leak": "d2", "frame": "e04", "mole_view": mv}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        qdm.extract_carbon_sft(jsonl_dir=bad_dir)


def test_chat_template_enable_thinking_fallback():
    class Qwen3Tok:
        def __init__(self):
            self.seen_kwargs = None

        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False, **kwargs):
            self.seen_kwargs = dict(kwargs)
            return f"q3:{len(messages)}:{add_generation_prompt}:{kwargs.get('enable_thinking')}"

    class Qwen25Tok:
        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
            _ = tokenize
            return f"q25:{len(messages)}:{add_generation_prompt}"

    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "obs"}]
    t3 = Qwen3Tok()
    out3 = qdm.apply_chat(t3, msgs, add_gen=True)
    assert out3 == "q3:2:True:False"
    assert t3.seen_kwargs == {"enable_thinking": False}

    t25 = Qwen25Tok()
    out25 = qdm.apply_chat(t25, msgs, add_gen=True)
    assert out25 == "q25:2:True"


def test_anti_collapse_reward_advantage_and_lam_catch_update():
    bad = qdm.grpo_reward_task(({"seed": 120_000, "day": 1, "tier": "hard"}, "garbage output", 0.90))
    assert bad == {"reward": -1.0, "valid": False}

    r_low_lam = qdm.grpo_reward_task(
        ({"seed": 120_000, "day": 2, "tier": "easy"}, '{"leak": "none", "frame": "none"}', 0.50)
    )
    assert r_low_lam["valid"] is True
    expected_catch = 0.15 if r_low_lam["solver"][1] else -0.50
    assert math.isclose(r_low_lam["reward"], r_low_lam["regret"] + expected_catch - 0.20, rel_tol=1e-6)

    synthetic_batch = [
        {"reward": 1.0, "valid": True, "action": ["most_recipients", "decoy"]} for _ in range(5)
    ] + [
        {"reward": 1.0, "valid": True, "action": ["newest", "most_restricted_peer"]},
    ]
    adj, counts = qdm.apply_batch_diversity_penalty(synthetic_batch, freq_cap=0.40, penalty_scale=0.25)
    assert counts[("most_recipients", "decoy")] == 5
    expected_pen = 0.25 * ((5.0 / 6.0) - 0.40)
    for x in adj[:5]:
        assert math.isclose(x, 1.0 - expected_pen, rel_tol=1e-6)
    assert math.isclose(adj[5], 1.0, rel_tol=1e-6)

    adv = qdm.compute_group_advantages([0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0], group=4)
    assert len(adv) == 8
    assert abs(sum(adv[:4])) < 1e-6
    assert adv[0] < adv[1] < adv[2] < adv[3]
    assert all(abs(x) < 1e-6 for x in adv[4:])

    lam_up = qdm.update_lam_catch(0.90, batch_solver_acc=0.70, target_acc=0.89)
    assert lam_up > 0.90
    assert math.isclose(lam_up, 0.90 + 1.2 * (0.89 - 0.70), rel_tol=1e-6)

    lam_down = qdm.update_lam_catch(0.90, batch_solver_acc=1.00, target_acc=0.89)
    assert 0.40 <= lam_down < 0.90
    assert math.isclose(lam_down, 0.90 + 1.2 * (0.89 - 1.00), rel_tol=1e-6)

    assert qdm.update_lam_catch(2.95, batch_solver_acc=0.0, target_acc=0.89) == 3.0
    assert qdm.update_lam_catch(0.42, batch_solver_acc=1.0, target_acc=0.89) == 0.40

    cands = [
        ("collapsed", Path("/tmp/c1"), {"solver": {"acc": 0.92}, "distinct_actions": 1, "min_regret": 0.65}),
        ("diverse_ok", Path("/tmp/c2"), {"solver": {"acc": 0.90}, "distinct_actions": 3, "min_regret": 0.52}),
        ("uncatchable", Path("/tmp/c3"), {"solver": {"acc": 0.70}, "distinct_actions": 4, "min_regret": 0.80}),
    ]
    assert qdm.select_winner_candidate(cands)[0] == "diverse_ok"


def test_qwen_mole_policy_mock_generator_and_merge_unmerge_guard():
    pol = qdm.QwenMolePolicy(
        generate_fn=lambda _: '{"leak": "most_recipients", "frame": "decoy"}',
    )
    v = MoleView(
        day=2,
        docs=(
            MoleDoc("d1", "Small note", 4, 1),
            MoleDoc("d2", "Company bulletin", 21, 0),
        ),
        days_since_last_leak=1,
        i_am_restricted=0,
        n_restricted_colleagues=1,
        recent_low_recipient_docs=1,
        peers=("e01", "e02", "e03"),
        restricted_peers=("e02",),
        decoy="e03",
        can_leak=True,
    )
    d1 = pol.decide(v, random.Random(0))
    d2 = pol.decide(v, random.Random(0))
    assert d1 == {"leak": "d2", "frame": "e03"}
    assert d2 == d1
    assert pol.calls == 1
    assert pol.invalid == 0
    assert pol.actions == [("most_recipients", "decoy"), ("most_recipients", "decoy")]

    bad_pol = qdm.QwenMolePolicy(generate_fn=lambda _: "not json at all")
    d_bad = bad_pol.decide(v, random.Random(0))
    assert d_bad["leak"] in {"d1", "d2"}
    assert d_bad["frame"] is None
    assert bad_pol.invalid == 1

    class MockCfg:
        use_cache = False

    class MockPeftModel:
        def __init__(self):
            self.config = MockCfg()
            self.events: list[str] = []
            self.is_merged = False

        def merge_adapter(self):
            self.events.append("merge")
            self.is_merged = True

        def unmerge_adapter(self):
            self.events.append("unmerge")
            self.is_merged = False

    mock_model = MockPeftModel()
    rows, summ = qdm.eval_full_episodes(
        mock_model,
        None,
        "cpu",
        seeds=[195_000],
        tier="easy",
        generate_fn=lambda _: '{"leak": "most_recipients", "frame": "decoy"}',
    )
    assert len(rows) == 1
    assert mock_model.events == ["merge", "unmerge"]
    assert mock_model.is_merged is False
    assert mock_model.config.use_cache is False
    assert summ["distinct_actions"] == 1
    assert summ["invalid_generations"] == 0


def test_tiny_synthetic_sft_and_grpo_smoke(tmp_path):
    if any(importlib.util.find_spec(m) is None for m in ("torch", "transformers", "peft")):
        pytest.skip("torch/transformers/peft not installed")

    sft_path = tmp_path / "sft_tiny.jsonl"
    mv = _sample_mole_view_dict()
    sft_rows = [
        {
            "prompt": qdm.render_dict_view(mv),
            "target": json.dumps({"leak": "most_recipients", "frame": "decoy"}),
            "action": ["most_recipients", "decoy"],
            "source": "gemini-4-carbon",
            "seed": 0,
            "day": 2,
            "trap_only": False,
        },
        {
            "prompt": qdm.render_dict_view(_sample_mole_view_dict(day=3)),
            "target": json.dumps({"leak": "newest", "frame": "most_restricted_peer"}),
            "action": ["newest", "most_restricted_peer"],
            "source": "gemini-4-carbon",
            "seed": 1,
            "day": 3,
            "trap_only": False,
        },
    ]
    sft_path.write_text("".join(json.dumps(r) + "\n" for r in sft_rows), encoding="utf-8")

    sft_out = tmp_path / "sft_out"
    sft_meta = qdm.main(
        [
            "sft",
            "--tiny",
            "--model",
            "tiny-synthetic",
            "--data",
            str(sft_path),
            "--epochs",
            "1",
            "--batch-size",
            "2",
            "--out",
            str(sft_out),
        ]
    )
    assert (Path(sft_meta["adapter_dir"]) / "adapter_config.json").is_file()

    prompts_path = tmp_path / "prompts.jsonl"
    prompts_path.write_text(
        json.dumps({"seed": 120_000, "day": 2, "tier": "hard", "prompt": sft_rows[0]["prompt"]}) + "\n",
        encoding="utf-8",
    )
    grpo_out = tmp_path / "grpo_out"
    grpo_meta = qdm.main(
        [
            "grpo",
            "--tiny",
            "--model",
            "tiny-synthetic",
            "--sft-adapter",
            sft_meta["adapter_dir"],
            "--prompts",
            str(prompts_path),
            "--steps",
            "1",
            "--prompts-per-step",
            "1",
            "--group",
            "2",
            "--eval-every",
            "1",
            "--val-seeds",
            "1",
            "--workers",
            "1",
            "--out",
            str(grpo_out),
        ]
    )
    assert (Path(grpo_meta["adapter_dir"]) / "adapter_config.json").is_file()
    assert (grpo_out / "grpo_curve.jsonl").is_file()
